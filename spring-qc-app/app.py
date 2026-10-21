import os
import sys
import re
import json
import base64
import uuid
import time
import secrets
import hashlib
import tempfile
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import yaml
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from detector import SpringDetector, get_roi_from_config  # noqa: E402

CONFIG_PATH = BASE_DIR / 'config.yaml'
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# PostgreSQL connection - overridden by DATABASE_URL in docker-compose. The
# default targets a local Postgres (or one started via `docker compose up db`).
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://spring_qc:spring_qc@localhost:5432/spring_qc',
)

# Starlette spools each multipart upload part to a temp file once it outgrows
# a small in-memory buffer, using Python's default temp dir - normally the
# system drive (C: on Windows). Video uploads here run into the hundreds of
# MB to low GB, and the system drive can run tight on space independently of
# this app - point temp spooling at this project's own drive instead so a
# full C: doesn't silently break every upload.
_TEMP_DIR = BASE_DIR / '_tmp'
_TEMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_TEMP_DIR)

app = FastAPI(title='Spring QC - Admin / Operator')

jobs = {}  # job_id -> Job
jobs_lock = threading.Lock()


def get_db():
    # autocommit: each statement commits on its own, matching how the old
    # sqlite code behaved - no explicit .commit() needed anywhere.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def init_db():
    # The DB container may still be starting when the app boots - wait for it.
    conn = None
    for attempt in range(60):
        try:
            conn = get_db()
            break
        except psycopg.OperationalError:
            if attempt == 0:
                print(f'Waiting for PostgreSQL at {DATABASE_URL.rsplit("@", 1)[-1]} ...')
            time.sleep(1)
    if conn is None:
        raise RuntimeError('Could not connect to PostgreSQL after 60s')

    conn.execute('''CREATE TABLE IF NOT EXISTS operators (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        machine_no TEXT,
        pin_salt TEXT,
        pin_hash TEXT,
        roi_points TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )''')
    # Postgres can add missing columns idempotently - covers upgrades from an
    # older schema without the PRAGMA introspection the sqlite version needed.
    for col, decl in (('machine_no', 'TEXT'), ('pin_salt', 'TEXT'), ('pin_hash', 'TEXT'), ('roi_points', 'TEXT')):
        conn.execute(f'ALTER TABLE operators ADD COLUMN IF NOT EXISTS {col} {decl}')
    conn.execute('''CREATE TABLE IF NOT EXISTS inspections (
        id SERIAL PRIMARY KEY,
        job_id TEXT NOT NULL,
        source_type TEXT,
        source_label TEXT,
        operator TEXT,
        s_no INTEGER NOT NULL,
        in_time_sec DOUBLE PRECISION,
        out_time_sec DOUBLE PRECISION,
        duration_sec DOUBLE PRECISION,
        defect TEXT NOT NULL,
        decided_at TIMESTAMPTZ NOT NULL,
        image_count INTEGER DEFAULT 0,
        started_at TIMESTAMPTZ
    )''')
    # started_at = wall-clock time the job began; in_time_sec / out_time_sec are
    # offsets from it, so real IN/OUT clock times = started_at + those offsets.
    conn.execute('ALTER TABLE inspections ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_inspections_operator ON inspections (operator)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_inspections_decided_at ON inspections (decided_at)')
    # Saved operator->source assignments (one per operator) so the admin's
    # setup survives a restart instead of only living while a job runs.
    conn.execute('''CREATE TABLE IF NOT EXISTS assignments (
        operator TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,          -- 'rtsp' | 'upload'
        source_name TEXT,                   -- friendly label the admin gives it
        rtsp_url TEXT,
        file_id TEXT,
        file_name TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )''')
    conn.close()


init_db()


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


class StartRequest(BaseModel):
    source_type: str = 'rtsp'  # 'rtsp' or 'upload'
    url: str | None = None
    file_id: str | None = None
    operator: str | None = None
    label: str | None = None   # friendly source name; falls back to url / filename


class Job:
    def __init__(self, job_id, source_kind, source, config, model, label=None, operator=None, start_serial=1):
        self.job_id = job_id
        self.source_kind = source_kind  # 'rtsp' or 'upload'
        self.source = source
        self.label = label or source
        self.operator = operator
        self.start_serial = start_serial
        self.config = config
        self.model = model
        self.status = 'starting'
        self.started_at = None  # set when run() flips status to 'running'
        self.error = None
        self.done = threading.Event()
        self.stop_event = threading.Event()
        self.frame_lock = threading.Lock()
        self.latest_jpg = None
        # Broadcast log: every websocket connection to this job (admin +
        # operator can both be connected at once) keeps its own read cursor
        # into this list, instead of racing to pull off a shared queue.
        self.events_log = []
        self.events_log_lock = threading.Lock()
        self.result = None
        self.thread = None
        self.detector = None
        # Test-video playback is paced to roughly real time (via frame fps)
        # so an operator testing a recording sees the same "one spring at a
        # time" cadence as a live camera, instead of it flashing by instantly.
        self.frame_interval = 1.0 / 30.0
        self.last_frame_time = 0.0

    def stop(self):
        self.stop_event.set()

    def _paced(self):
        now = time.time()
        remaining = self.frame_interval - (now - self.last_frame_time)
        if remaining > 0:
            time.sleep(remaining)
        self.last_frame_time = time.time()

    def run(self):
        self.status = 'running'
        self.started_at = datetime.now(timezone.utc)
        if self.source_kind == 'upload':
            self.frame_interval = 1.0 / (video_fps(self.source) or 30.0)
        self.detector = SpringDetector(
            self.model,
            self.config['model'],
            self.config.get('tracking', {}),
            self.config.get('events', {}),
            get_roi_from_config(self.config),
            on_frame=self._on_frame,
            on_event=self._on_event,
            start_serial=self.start_serial,
        )
        try:
            self.result = self.detector.run(
                self.source,
                max_frames=None,
                writer=None,
                should_stop=self.stop_event.is_set,
            )
            self.status = 'completed'
        except Exception as e:
            self.status = 'error'
            self.error = str(e)
            self._log_event({'type': 'error', 'message': str(e)})
        finally:
            flush_pending_unknown(self)
            self._log_event({'type': 'completed', 'status': self.status})
            self.done.set()

    def _log_event(self, event):
        with self.events_log_lock:
            self.events_log.append(event)

    def _on_frame(self, annotated_frame):
        if self.source_kind == 'upload':
            self._paced()
        h, w = annotated_frame.shape[:2]
        max_w = 1280
        if w > max_w:
            scale = max_w / float(w)
            annotated_frame = cv2.resize(annotated_frame, (max_w, int(h * scale)))
        ok, buf = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            with self.frame_lock:
                self.latest_jpg = buf.tobytes()

    def _on_event(self, event):
        payload = self._jsonable(event)
        self._log_event({**payload, 'type': 'event'})

    @staticmethod
    def _jsonable(obj):
        import numpy as np
        if isinstance(obj, dict):
            return {k: Job._jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [Job._jsonable(v) for v in obj]
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return Job._jsonable(obj.tolist())
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj


def resolve_device(device):
    import torch
    if device is None or str(device).lower() in ('auto', ''):
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    return str(device)


def model_from_config(config):
    dev = config['model'].get('device', 'auto')
    p = Path(config['model']['path'])
    if not p.is_absolute():
        p = BASE_DIR / p
    model = YOLO(str(p))
    model = model.to(resolve_device(dev))
    return model


def video_fps(path):
    try:
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return float(fps) if fps and fps > 0 else None
    except Exception:
        return None


def defect_output_dir():
    cfg = load_config()
    d = cfg.get('events', {}).get('defect', {}).get('output_dir', 'Output/defects')
    p = Path(d)
    return p if p.is_absolute() else (BASE_DIR / p)


def write_defect_record(job, s_no, defect):
    """Persist one spring's decision: images to disk (namespaced by job_id so
    S.No, which restarts at 1 per job, never collides across concurrent
    jobs/operators) and a row in the inspections table for the dashboards."""
    det = getattr(job, 'detector', None)
    if det is None:
        return False
    rec = det._pending.get(int(s_no))
    if not rec:
        return False
    rec['defect'] = defect
    d = defect_output_dir() / job.job_id / str(int(s_no))
    d.mkdir(parents=True, exist_ok=True)
    summary = {k: v for k, v in rec.items() if k != 'frames_b64'}
    with open(d / 'result.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    frames = rec.get('frames_b64', [])
    for i, b64 in enumerate(frames, start=1):
        with open(d / f'frame_{i}.jpg', 'wb') as f:
            f.write(base64.b64decode(b64))

    conn = get_db()
    conn.execute(
        '''INSERT INTO inspections
           (job_id, source_type, source_label, operator, s_no,
            in_time_sec, out_time_sec, duration_sec, defect, decided_at, image_count, started_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (job.job_id, job.source_kind, job.label, job.operator, int(s_no),
         rec.get('in_time_sec'), rec.get('out_time_sec'), rec.get('duration_sec'),
         defect, datetime.now(timezone.utc), len(frames), getattr(job, 'started_at', None)),
    )
    conn.close()
    return True


def flush_pending_unknown(job):
    det = getattr(job, 'detector', None)
    if det is None:
        return
    for s_no in list(getattr(det, '_pending', {}).keys()):
        if det._pending[s_no].get('defect') is None:
            write_defect_record(job, s_no, 'unknown')


# ---------------------------------------------------------------- pages ----

@app.get('/')
def index():
    return FileResponse(BASE_DIR / 'static' / 'index.html')


@app.get('/admin')
def admin_page():
    return FileResponse(BASE_DIR / 'static' / 'admin.html')


@app.get('/operator')
def operator_page():
    return FileResponse(BASE_DIR / 'static' / 'operator.html')


@app.get('/reports')
def reports_page():
    return FileResponse(BASE_DIR / 'static' / 'reports.html')


@app.get('/monitor')
def monitor_page():
    return FileResponse(BASE_DIR / 'static' / 'monitor.html')


# ---------------------------------------------------------- operators API --

class OperatorCreate(BaseModel):
    name: str
    machine_no: str | None = None
    pin: str | None = None  # required when creating; optional when just updating machine_no


class OperatorVerify(BaseModel):
    name: str
    pin: str


PIN_RE = re.compile(r'^\d{4}$')


def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt, hashlib.sha256((salt + pin).encode('utf-8')).hexdigest()


def _running_jobs_by_operator():
    assigned = {}
    for job in jobs.values():
        if job.operator and job.status in ('starting', 'running'):
            assigned[job.operator] = {
                'job_id': job.job_id, 'label': job.label,
                'source_type': job.source_kind, 'status': job.status,
            }
    return assigned


@app.get('/operators')
def list_operators():
    conn = get_db()
    rows = conn.execute(
        'SELECT name, machine_no, roi_points FROM operators ORDER BY LOWER(name)'
    ).fetchall()
    conn.close()
    assigned = _running_jobs_by_operator()
    return [
        {
            'name': r['name'],
            'machine_no': r['machine_no'],
            'roi_points': json.loads(r['roi_points']) if r['roi_points'] else None,
            'assignment': assigned.get(r['name']),
        }
        for r in rows
    ]


@app.post('/operators')
def add_operator(body: OperatorCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Operator name required')
    machine_no = (body.machine_no or '').strip() or None

    conn = get_db()
    try:
        existing = conn.execute('SELECT id FROM operators WHERE name = %s', (name,)).fetchone()
        if existing:
            if body.pin:
                if not PIN_RE.match(body.pin):
                    raise HTTPException(400, 'PIN must be exactly 4 digits')
                salt, pin_hash = hash_pin(body.pin)
                conn.execute(
                    'UPDATE operators SET machine_no = %s, pin_salt = %s, pin_hash = %s WHERE name = %s',
                    (machine_no, salt, pin_hash, name),
                )
            else:
                conn.execute('UPDATE operators SET machine_no = %s WHERE name = %s', (machine_no, name))
        else:
            if not body.pin or not PIN_RE.match(body.pin):
                raise HTTPException(400, 'PIN must be exactly 4 digits')
            salt, pin_hash = hash_pin(body.pin)
            conn.execute(
                'INSERT INTO operators (name, machine_no, pin_salt, pin_hash) VALUES (%s, %s, %s, %s)',
                (name, machine_no, salt, pin_hash),
            )
    finally:
        conn.close()
    return {'ok': True, 'name': name}


class OperatorRoiUpdate(BaseModel):
    roi_points: list[list[int]]


@app.post('/operators/{name}/roi')
def save_operator_roi(name: str, body: OperatorRoiUpdate):
    if len(body.roi_points) < 3:
        raise HTTPException(400, 'ROI needs at least 3 points')
    pts = [[int(x), int(y)] for x, y in body.roi_points]
    conn = get_db()
    existing = conn.execute('SELECT id FROM operators WHERE name = %s', (name,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, 'Operator not found')
    conn.execute('UPDATE operators SET roi_points = %s WHERE name = %s', (json.dumps(pts), name))
    conn.close()

    # Push straight to any running job for this operator so a live stream
    # switches to the new ROI on its next frame - no re-save / restart needed.
    applied_live = False
    with jobs_lock:
        for job in jobs.values():
            if job.operator == name and job.status in ('starting', 'running'):
                job.config.setdefault('roi', {})['points'] = pts
                det = getattr(job, 'detector', None)
                if det is not None and hasattr(det, 'set_roi'):
                    det.set_roi(pts)
                    applied_live = True
    return {'ok': True, 'name': name, 'roi_points': pts, 'applied_live': applied_live}


@app.post('/operators/verify')
def verify_operator(body: OperatorVerify):
    conn = get_db()
    row = conn.execute(
        'SELECT pin_salt, pin_hash FROM operators WHERE name = %s', (body.name,)
    ).fetchone()
    conn.close()
    if not row or not row['pin_hash']:
        raise HTTPException(404, 'Operator not configured')
    _, actual = hash_pin(body.pin, row['pin_salt'])
    if actual != row['pin_hash']:
        raise HTTPException(401, 'Incorrect PIN')
    return {'ok': True}


@app.delete('/operators/{name}')
def delete_operator(name: str):
    if _running_jobs_by_operator().get(name):
        raise HTTPException(409, f"Operator '{name}' has a running job - stop it first")
    conn = get_db()
    conn.execute('DELETE FROM operators WHERE name = %s', (name,))
    conn.execute('DELETE FROM assignments WHERE operator = %s', (name,))
    conn.close()
    return {'ok': True}


# ------------------------------------------------------- assignments API ---

class AssignmentUpsert(BaseModel):
    source_type: str                  # 'rtsp' | 'upload'
    source_name: str | None = None
    rtsp_url: str | None = None
    file_id: str | None = None
    file_name: str | None = None


@app.get('/assignments')
def list_assignments():
    conn = get_db()
    rows = conn.execute('SELECT * FROM assignments ORDER BY LOWER(operator)').fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.put('/assignments/{operator}')
def upsert_assignment(operator: str, body: AssignmentUpsert):
    operator = operator.strip()
    if body.source_type not in ('rtsp', 'upload'):
        raise HTTPException(400, "source_type must be 'rtsp' or 'upload'")
    if body.source_type == 'rtsp' and not (body.rtsp_url or '').strip():
        raise HTTPException(400, 'rtsp_url required for an RTSP assignment')
    if body.source_type == 'upload' and not (body.file_id or '').strip():
        raise HTTPException(400, 'file_id required for a test-video assignment')
    conn = get_db()
    if not conn.execute('SELECT 1 FROM operators WHERE name = %s', (operator,)).fetchone():
        conn.close()
        raise HTTPException(404, f"Unknown operator '{operator}'")
    conn.execute(
        '''INSERT INTO assignments
               (operator, source_type, source_name, rtsp_url, file_id, file_name, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (operator) DO UPDATE SET
               source_type = EXCLUDED.source_type,
               source_name = EXCLUDED.source_name,
               rtsp_url    = EXCLUDED.rtsp_url,
               file_id     = EXCLUDED.file_id,
               file_name   = EXCLUDED.file_name,
               updated_at  = now()''',
        (operator, body.source_type, (body.source_name or '').strip() or None,
         (body.rtsp_url or '').strip() or None, (body.file_id or '').strip() or None,
         body.file_name),
    )
    conn.close()
    return {'ok': True, 'operator': operator}


@app.delete('/assignments/{operator}')
def delete_assignment(operator: str):
    conn = get_db()
    conn.execute('DELETE FROM assignments WHERE operator = %s', (operator,))
    conn.close()
    return {'ok': True}


# ------------------------------------------------------------- admin API ---

@app.get('/config')
def get_config():
    cfg = load_config()
    roi = get_roi_from_config(cfg)
    return {
        'model_path': cfg['model']['path'],
        'conf_threshold': cfg['model']['conf_threshold'],
        'iou_threshold': cfg['model']['iou_threshold'],
        'device': cfg['model']['device'],
        'tracking_enabled': cfg.get('tracking', {}).get('enabled', True),
        'tracker': cfg.get('tracking', {}).get('tracker', 'bytetrack'),
        'recover_frames': cfg.get('tracking', {}).get('recover_frames', 30),
        'recover_dist': cfg.get('tracking', {}).get('recover_dist', 120),
        'out_frames': cfg.get('tracking', {}).get('out_frames', 90),
        'confirm_frames': cfg.get('tracking', {}).get('confirm_frames', 100),
        'events_enabled': cfg.get('events', {}).get('enabled', True),
        'roi_points': [list(p) for p in roi] if roi else [],
    }


class ConfigUpdate(BaseModel):
    model_path: str | None = None
    conf_threshold: float | None = None
    iou_threshold: float | None = None
    device: str | None = None
    tracking_enabled: bool | None = None
    tracker: str | None = None
    recover_frames: int | None = None
    recover_dist: int | None = None
    out_frames: int | None = None
    confirm_frames: int | None = None
    events_enabled: bool | None = None


@app.post('/save-config')
def save_config(upd: ConfigUpdate):
    cfg = load_config()
    if upd.model_path is not None:
        cfg['model']['path'] = upd.model_path
    if upd.conf_threshold is not None:
        cfg['model']['conf_threshold'] = upd.conf_threshold
    if upd.iou_threshold is not None:
        cfg['model']['iou_threshold'] = upd.iou_threshold
    if upd.device is not None:
        cfg['model']['device'] = upd.device
    if upd.tracking_enabled is not None:
        cfg.setdefault('tracking', {})['enabled'] = upd.tracking_enabled
    if upd.tracker is not None:
        cfg.setdefault('tracking', {})['tracker'] = upd.tracker
    if upd.recover_frames is not None:
        cfg.setdefault('tracking', {})['recover_frames'] = upd.recover_frames
    if upd.recover_dist is not None:
        cfg.setdefault('tracking', {})['recover_dist'] = upd.recover_dist
    if upd.out_frames is not None:
        cfg.setdefault('tracking', {})['out_frames'] = upd.out_frames
    if upd.confirm_frames is not None:
        cfg.setdefault('tracking', {})['confirm_frames'] = upd.confirm_frames
    if upd.events_enabled is not None:
        cfg.setdefault('events', {})['enabled'] = upd.events_enabled
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    return {'ok': True}


@app.get('/gpu')
def gpu_info():
    import torch
    available = torch.cuda.is_available()
    cfg = load_config()
    return {
        'available': available,
        'gpu_name': torch.cuda.get_device_name(0) if available else None,
        'runs_on': resolve_device(cfg['model'].get('device', 'auto')),
    }


class RoiUpdate(BaseModel):
    roi_points: list[list[int]]


@app.post('/save-roi')
def save_roi(upd: RoiUpdate):
    if len(upd.roi_points) < 3:
        raise HTTPException(400, 'ROI needs at least 3 points')
    cfg = load_config()
    cfg['roi'] = {'points': [[int(x), int(y)] for x, y in upd.roi_points]}
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    return {'ok': True, 'roi_points': cfg['roi']['points']}


@app.get('/frame')
def get_frame(url: str | None = None, file_id: str | None = None):
    source = _resolve_upload(file_id) if file_id else url
    if not source:
        raise HTTPException(400, 'Provide url (RTSP) or file_id (uploaded video)')
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise HTTPException(400, 'Could not open source')
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(400, 'Could not read a frame from source')
        ok, buf = cv2.imencode('.jpg', frame)
        if not ok:
            raise HTTPException(500, 'Could not encode frame')
        return Response(content=buf.tobytes(), media_type='image/jpeg')
    finally:
        cap.release()


def _resolve_upload(file_id):
    matches = list(UPLOAD_DIR.glob(f'{file_id}.*'))
    if not matches:
        raise HTTPException(404, 'Uploaded video not found')
    return str(matches[0])


@app.post('/upload')
async def upload_video(request: Request):
    # FastAPI's `UploadFile = File(...)` shortcut calls Request.form() with
    # its defaults, and Starlette defaults max_part_size to just 1 MiB - any
    # video (always far bigger) then fails immediately with a generic
    # "error parsing the body", well before any size/emptiness check of ours
    # ever runs. Parsing the form ourselves lets us raise that ceiling.
    form = await request.form(max_part_size=4 * 1024 * 1024 * 1024)  # 4 GiB/part
    file = form.get('file')
    if file is None or not hasattr(file, 'filename'):
        raise HTTPException(400, "No 'file' field in the upload")

    file_id = uuid.uuid4().hex
    ext = Path(file.filename or 'video').suffix or '.mp4'
    dest = UPLOAD_DIR / f'{file_id}{ext}'
    try:
        # Stream to disk in chunks rather than loading the whole file into
        # memory at once - test recordings here run into the hundreds of MB.
        with open(dest, 'wb') as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f'Upload failed: {e}')
    finally:
        await file.close()
    if not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            400,
            f"'{file.filename}' arrived as 0 bytes. If it's a cloud-synced file "
            "(OneDrive/Google Drive 'on-demand' placeholder), make sure it's fully "
            "downloaded locally first, then try again."
        )
    return {'file_id': file_id, 'filename': file.filename}


@app.post('/start')
def start_job(req: StartRequest):
    cfg = load_config()

    if req.source_type == 'upload':
        if not req.file_id:
            raise HTTPException(400, 'file_id required')
        source = _resolve_upload(req.file_id)
        label = Path(source).name
        source_kind = 'upload'
    else:
        if not req.url:
            raise HTTPException(400, 'RTSP url required')
        source = req.url
        label = req.url
        source_kind = 'rtsp'

    if (req.label or '').strip():
        label = req.label.strip()

    operator = (req.operator or '').strip() or None
    start_serial = 1
    if operator:
        already = _running_jobs_by_operator().get(operator)
        if already:
            raise HTTPException(
                409,
                f"Operator '{operator}' is already assigned to a running job "
                f"({already['label']}). Stop it first or pick another operator."
            )
        conn = get_db()
        # Each operator's ROI is their own (different cameras point at
        # different geometry) - use it if they've saved one, instead of the
        # single shared config.yaml default that every job used to share.
        op_row = conn.execute(
            'SELECT roi_points FROM operators WHERE name = %s', (operator,)
        ).fetchone()
        if op_row and op_row['roi_points']:
            cfg['roi'] = {'points': json.loads(op_row['roi_points'])}
        # S.No must keep counting up for this operator across separate Go
        # Live sessions, not restart at 1 every time - otherwise the same
        # operator ends up with repeated S.No values in their own history.
        max_row = conn.execute(
            'SELECT MAX(s_no) AS m FROM inspections WHERE operator = %s', (operator,)
        ).fetchone()
        conn.close()
        if max_row and max_row['m']:
            start_serial = int(max_row['m']) + 1

    probe = cv2.VideoCapture(source)
    ok = probe.isOpened()
    probe.release()
    if not ok:
        raise HTTPException(400, 'Could not open video source')

    model = model_from_config(cfg)
    job_id = uuid.uuid4().hex
    job = Job(job_id, source_kind, source, cfg, model, label=label, operator=operator, start_serial=start_serial)
    job.thread = threading.Thread(target=job.run, daemon=True)
    with jobs_lock:
        jobs[job_id] = job
    job.thread.start()
    return {'job_id': job_id, 'source_type': source_kind, 'label': label, 'operator': operator}


@app.post('/stop/{job_id}')
def stop_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, 'Job not found')
    job.stop()
    return {'job_id': job_id, 'status': 'stopping'}


@app.get('/jobs')
def list_jobs(operator: str | None = None):
    result = [
        {
            'job_id': job_id,
            'source_type': job.source_kind,
            'label': job.label,
            'operator': job.operator,
            'status': job.status,
            'error': job.error,
        }
        for job_id, job in jobs.items()
    ]
    if operator:
        result = [j for j in result if (j['operator'] or '').lower() == operator.lower()]
    return result


# --------------------------------------------------------- operator API ---

class DefectUpdate(BaseModel):
    job_id: str
    s_no: int
    defect: str


@app.post('/save-defect')
def save_defect(upd: DefectUpdate):
    if upd.defect not in ('defective', 'ok', 'unknown'):
        raise HTTPException(400, "defect must be 'defective' or 'ok'")
    job = jobs.get(upd.job_id)
    if job is None or getattr(job, 'detector', None) is None:
        raise HTTPException(404, 'No active detector for this job')
    if not write_defect_record(job, upd.s_no, upd.defect):
        raise HTTPException(404, f'No pending spring for S.No {upd.s_no}')
    return {'ok': True, 's_no': upd.s_no, 'defect': upd.defect}


@app.get('/defect-image/{job_id}/{s_no}/{frame_no}')
def get_defect_image(job_id: str, s_no: int, frame_no: int):
    p = defect_output_dir() / job_id / str(s_no) / f'frame_{frame_no}.jpg'
    if not p.exists():
        raise HTTPException(404, 'Image not found')
    return FileResponse(p, media_type='image/jpeg')


# ----------------------------------------------------------- reports API --

def _date_clause(date, days, params, existing_where):
    """Build the WHERE fragment scoping decided_at to either one exact
    calendar date (takes precedence) or a rolling 'last N days' window."""
    if date:
        existing_where.append('decided_at::date = %s::date')
        params.append(date)
    elif days:
        existing_where.append("decided_at >= now() - %s::interval")
        params.append(f'{int(days)} days')


@app.get('/reports/summary')
def reports_summary(operator: str | None = None, days: int | None = None, date: str | None = None):
    conn = get_db()
    where = []
    params = []
    if operator:
        where.append('operator = %s')
        params.append(operator)
    _date_clause(date, days, params, where)
    q = 'SELECT defect, COUNT(*) AS c FROM inspections'
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' GROUP BY defect'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    counts = {r['defect']: r['c'] for r in rows}
    total = sum(counts.values())
    return {
        'total': total,
        'defective': counts.get('defective', 0),
        'ok': counts.get('ok', 0),
        'unknown': counts.get('unknown', 0),
    }


@app.get('/reports/operators-summary')
def reports_operators_summary(days: int | None = None, date: str | None = None):
    conn = get_db()
    where = []
    params = []
    _date_clause(date, days, params, where)
    q = '''
        SELECT operator,
               COUNT(*) AS total,
               SUM(CASE WHEN defect='defective' THEN 1 ELSE 0 END) AS defective,
               SUM(CASE WHEN defect='ok' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN defect='unknown' THEN 1 ELSE 0 END) AS unknown,
               MAX(decided_at) AS last_decision
        FROM inspections
    '''
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' GROUP BY operator ORDER BY total DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get('/reports/daily')
def reports_daily(operator: str | None = None, days: int = 30, date: str | None = None):
    """Per-day OK/defective/unknown counts for the trend chart and an
    operator's drill-down sparkline. Days with zero inspections simply don't
    appear in the result - the caller fills the gaps for a continuous axis."""
    conn = get_db()
    where = []
    params = []
    if operator:
        where.append('operator = %s')
        params.append(operator)
    _date_clause(date, days, params, where)
    q = '''
        SELECT decided_at::date AS day,
               COUNT(*) AS total,
               SUM(CASE WHEN defect='ok' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN defect='defective' THEN 1 ELSE 0 END) AS defective,
               SUM(CASE WHEN defect='unknown' THEN 1 ELSE 0 END) AS unknown
        FROM inspections
    '''
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' GROUP BY decided_at::date ORDER BY decided_at::date'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    # day comes back as a date object - normalise to YYYY-MM-DD for the client
    return [{**r, 'day': r['day'].isoformat()} for r in rows]


@app.get('/reports/records')
def reports_records(operator: str | None = None, job_id: str | None = None, limit: int = 300, date: str | None = None):
    conn = get_db()
    q = 'SELECT * FROM inspections'
    clauses = []
    params = []
    if operator:
        clauses.append('operator = %s')
        params.append(operator)
    if job_id:
        clauses.append('job_id = %s')
        params.append(job_id)
    if date:
        clauses.append('decided_at::date = %s::date')
        params.append(date)
    if clauses:
        q += ' WHERE ' + ' AND '.join(clauses)
    q += ' ORDER BY id DESC LIMIT %s'
    params.append(max(1, min(limit, 2000)))
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get('/reports/export.xlsx')
def reports_export(
    operator: str | None = None,
    date: str | None = None,
    days: int | None = None,
    defect: str | None = None,          # 'ok' | 'defective' | 'unknown' | None (all)
    include_images: bool = True,
    images_per_row: int = 3,
    limit: int = 5000,
):
    """Build an .xlsx of matching inspections: a Summary sheet plus one
    Inspections row per spring, with up to `images_per_row` captured frames
    embedded to the right of each row."""
    try:
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.drawing.image import Image as XLImage
        from PIL import Image as PILImage
    except ImportError as e:
        raise HTTPException(500, f'Excel export needs openpyxl + pillow installed: {e}')

    images_per_row = max(0, min(int(images_per_row), 6))
    if not include_images:
        images_per_row = 0

    conn = get_db()
    where, params = [], []
    if operator and operator != 'all':
        where.append('operator = %s')
        params.append(operator)
    if defect and defect != 'all':
        where.append('defect = %s')
        params.append(defect)
    _date_clause(date, days, params, where)
    q = 'SELECT * FROM inspections'
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' ORDER BY decided_at DESC, id DESC LIMIT %s'
    params.append(max(1, min(int(limit), 20000)))
    rows = conn.execute(q, params).fetchall()
    conn.close()

    # Real IN/OUT clock times = job start + the in/out offsets. Fall back to
    # anchoring on decided_at (operator decides right after OUT) for old rows
    # saved before started_at was recorded. Then order the sheet by IN time.
    def clock_pair(r):
        st = r.get('started_at')
        it, ot = r.get('in_time_sec'), r.get('out_time_sec')
        if st is not None and it is not None:
            return st + timedelta(seconds=it), st + timedelta(seconds=ot if ot is not None else it)
        dec, dur = r.get('decided_at'), r.get('duration_sec')
        if dec is not None and dur is not None:
            return dec - timedelta(seconds=dur), dec
        return None, r.get('decided_at')

    for r in rows:
        r['_in_clock'], r['_out_clock'] = clock_pair(r)
    rows.sort(key=lambda r: r['_in_clock'] or r['decided_at'])
    for i, r in enumerate(rows, start=1):
        r['_seq'] = i          # S.No follows IN-time order (1 = earliest)
    rows.reverse()             # ...but list newest-first

    wb = Workbook()

    # ---- Summary sheet ----
    ws0 = wb.active
    ws0.title = 'Summary'
    counts = {'ok': 0, 'defective': 0, 'unknown': 0}
    for r in rows:
        counts[r['defect']] = counts.get(r['defect'], 0) + 1
    scope_txt = operator if (operator and operator != 'all') else 'All operators'
    if date:
        range_txt = f'Date {date}'
    elif days:
        range_txt = f'Last {int(days)} days'
    else:
        range_txt = 'All time'
    meta = [
        ('Spring QC — Inspection Export', ''),
        ('Generated', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')),
        ('Operator', scope_txt),
        ('Period', range_txt),
        ('Result filter', defect if (defect and defect != 'all') else 'All results'),
        ('', ''),
        ('Total inspections', len(rows)),
        ('Not defective', counts.get('ok', 0)),
        ('Defective', counts.get('defective', 0)),
        ('Unknown / skipped', counts.get('unknown', 0)),
    ]
    for i, (k, v) in enumerate(meta, start=1):
        ws0.cell(row=i, column=1, value=k)
        ws0.cell(row=i, column=2, value=v)
    ws0['A1'].font = Font(size=14, bold=True)
    ws0.column_dimensions['A'].width = 22
    ws0.column_dimensions['B'].width = 42

    # ---- Inspections sheet ----
    ws = wb.create_sheet('Inspections')
    headers = ['S.No', 'Spring No', 'Operator', 'Source', 'IN', 'OUT',
               'Duration (min)', 'Result', 'Camera / video', 'Job ID', 'Images', 'Decided at (UTC)']
    ws.append(headers)
    head_fill = PatternFill('solid', fgColor='0A5FB4')
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = head_fill
    for i, w in enumerate([7, 9, 18, 12, 20, 20, 13, 14, 34, 26, 8, 20], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'

    first_img_col = len(headers) + 2  # gap column between data and images
    for k in range(images_per_row):
        ws.column_dimensions[get_column_letter(first_img_col + k)].width = 24

    result_label = {'ok': 'Not defective', 'defective': 'Defective', 'unknown': 'Unknown'}
    img_root = defect_output_dir()
    MAX_TOTAL_IMAGES = 1500
    embedded = 0
    truncated = False

    def _clock(dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S') if hasattr(dt, 'strftime') else (str(dt) if dt else '')

    def _mins(sec):
        if not isinstance(sec, (int, float)):
            return None
        return f'{int(sec // 60)}:{int(round(sec % 60)):02d}'

    src_label = {'rtsp': 'RTSP', 'upload': 'Test video'}

    for i, r in enumerate(rows, start=1):
        ri = i + 1  # sheet row (header is row 1)
        decided = r['decided_at']
        ws.cell(row=ri, column=1, value=r['_seq'])                            # S.No (by IN time)
        ws.cell(row=ri, column=2, value=r['s_no'])                            # Spring No (tracker)
        ws.cell(row=ri, column=3, value=r['operator'] or '(unassigned)')
        ws.cell(row=ri, column=4, value=src_label.get(r['source_type'], r['source_type'] or ''))
        ws.cell(row=ri, column=5, value=_clock(r['_in_clock']))
        ws.cell(row=ri, column=6, value=_clock(r['_out_clock']))
        ws.cell(row=ri, column=7, value=_mins(r['duration_sec']))
        ws.cell(row=ri, column=8, value=result_label.get(r['defect'], r['defect']))
        ws.cell(row=ri, column=9, value=r['source_label'] or '')             # which camera / video
        ws.cell(row=ri, column=10, value=r['job_id'])
        ws.cell(row=ri, column=11, value=r['image_count'] or 0)
        ws.cell(row=ri, column=12, value=_clock(decided))

        if images_per_row and embedded < MAX_TOTAL_IMAGES:
            n = min(r['image_count'] or 0, images_per_row)
            placed = 0
            for fi in range(1, n + 1):
                src = img_root / r['job_id'] / str(r['s_no']) / f'frame_{fi}.jpg'
                if not src.exists():
                    continue
                try:
                    im = PILImage.open(src)
                    im.load()
                    im.thumbnail((150, 150))
                    buf = io.BytesIO()
                    im.convert('RGB').save(buf, format='JPEG', quality=80)
                    buf.seek(0)
                    ws.add_image(XLImage(buf), f'{get_column_letter(first_img_col + placed)}{ri}')
                    placed += 1
                    embedded += 1
                except Exception:
                    continue
                if embedded >= MAX_TOTAL_IMAGES:
                    truncated = True
                    break
            if placed:
                ws.row_dimensions[ri].height = 115

    if truncated:
        ws0.cell(row=len(meta) + 2, column=1,
                 value=f'Note: embedded images capped at {MAX_TOTAL_IMAGES}; later rows omit images.')

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    stamp = datetime.now().strftime('%Y%m%d-%H%M')
    scope_slug = re.sub(r'[^A-Za-z0-9_-]+', '_',
                        operator if (operator and operator != 'all') else 'all')
    fname = f'spring-qc_{scope_slug}_{stamp}.xlsx'
    return Response(
        content=out.read(),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )


# ------------------------------------------------------------- websocket --

@app.websocket('/ws/{job_id}')
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        await websocket.send_json({'type': 'error', 'message': 'Job not found'})
        await websocket.close()
        return

    last_jpg = None
    next_idx = 0  # this connection's own read cursor into job.events_log
    last_live_send = 0.0

    def pending_events():
        nonlocal next_idx
        with job.events_log_lock:
            new_events = job.events_log[next_idx:]
            next_idx = len(job.events_log)
        return new_events

    try:
        while True:
            with job.frame_lock:
                jpg = job.latest_jpg
            if jpg is not None and jpg != last_jpg:
                last_jpg = jpg
                await websocket.send_bytes(jpg)

            for ev in pending_events():
                await websocket.send_json(ev)

            if job.done.is_set():
                for ev in pending_events():
                    await websocket.send_json(ev)
                break

            # Live in-ROI elapsed timing (~every 0.3s) so both admin and
            # operator can show a running "inspecting" timer, not just a
            # snapshot on enter/exit.
            now = time.time()
            if now - last_live_send >= 0.3:
                last_live_send = now
                live = getattr(getattr(job, 'detector', None), 'live', {}) or {}
                await websocket.send_json({'type': 'live', 'live': Job._jsonable(live)})

            await websocket.send_json({'type': 'ping'})
            await asyncio.sleep(0.03)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
