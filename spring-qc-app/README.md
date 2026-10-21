# Spring QC

Vision-based quality-control station for a spring assembly line. A YOLO model
tracks springs through a region of interest (ROI); when a spring leaves the ROI
the operator marks it **Not defective**, **Defective**, or **Skip**, and every
decision — with timing (IN / OUT / duration) and captured frames — is stored in
PostgreSQL for reporting.

Deploying this on-site with an edge box, an admin PC, and touch-panel
operator stations on the shop-floor LAN? See **[`deploy/README.md`](deploy/README.md)**.

## What's in the box

| Path | Purpose |
|------|---------|
| `app.py` | FastAPI server — admin, operator, monitor and reports endpoints + the detection job manager |
| `detector.py` | The detection/tracking pipeline (YOLO + ByteTrack + ROI in/out + defect-frame capture) |
| `config.yaml` | Model path, thresholds, ROI default, tracker tuning (also editable from the admin **Settings** panel) |
| `model/best.pt` | The trained YOLO weights |
| `trackers/bytetrack_spring.yaml` | Tuned ByteTrack config |
| `static/` | The five web UIs (`index`, `admin`, `operator`, `monitor`, `reports`) |
| `static/app.css` · `static/nav.js` | Shared design system + navbar / theme-toggle used by every page |
| `Dockerfile`, `docker-compose.yml` | Container build + orchestration (app + PostgreSQL) |
| `migrate_from_sqlite.py` | One-shot import of an old `qc.db` into PostgreSQL |
| `requirements.txt` | Python dependencies |
| `run.bat` / `setup.bat` | Windows helpers for running without Docker |

Everything the app needs is inside this folder — no paths point outside it.

## Run with Docker (recommended)

Requires Docker Desktop / Docker Engine + Compose.

```bash
cp .env.example .env          # then edit .env and set a real POSTGRES_PASSWORD
docker compose up -d --build
```

That starts two containers:

- **`db`** — PostgreSQL 16, data in the `qc_pgdata` volume, exposed on host
  `localhost:5432` so **pgAdmin** (or any client) can connect with the
  credentials from `.env` (user `spring_qc`, db `spring_qc`).
- **`app`** — the web app on <http://localhost:8001>. Tables are created
  automatically on first start.

Open **<http://localhost:8001/admin>** to configure operators and assignments.

```bash
docker compose logs -f app      # follow logs
docker compose down             # stop (keeps data)
docker compose down -v          # stop and wipe the database + volumes
```

> Ports 5432 and 8001 must be free on the host. If you already run a local
> PostgreSQL or an older copy of this app, stop it first, or change the left
> side of the port mappings in `docker-compose.yml`.

### Persisted vs. rebuilt

| Kept across `down` / rebuild | Lost on `down -v` / not in the image |
|---|---|
| `qc_pgdata` — the whole database | uploaded videos (`qc_uploads`) unless `-v` |
| `./config.yaml` — Settings-panel + default-ROI edits (bind-mounted) | `qc_output`, `qc_tmp` |
| `./model/` — bind-mounted, swap `best.pt` and restart `app` | |

### Importing your old SQLite data

If you have a `qc.db` from before the PostgreSQL switch:

```bash
docker compose up -d db
# from this folder, in a Python env that has psycopg:
export DATABASE_URL=postgresql://spring_qc:<password>@localhost:5432/spring_qc
python migrate_from_sqlite.py qc.db
```

It copies operators (PINs and ROIs included) and inspection history; safe to
re-run.

### GPU (default) vs CPU

The image is built for **NVIDIA GPU (CUDA 12.4)** by default — RTSP streams
can't keep up on CPU once more than one job runs. This needs:

1. An NVIDIA GPU + current NVIDIA driver on the host.
2. The [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
   Docker Desktop (Windows/WSL2) ships it — just verify:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
   ```

Then `docker compose up -d --build`. `model.device: auto` in `config.yaml`
picks up the GPU automatically — verify with `GET /gpu`
(`{"available":true,"gpu_name":"...","runs_on":"cuda"}`).

**On a host with no NVIDIA GPU**, build the CPU variant instead:

```bash
TORCH_INDEX=https://download.pytorch.org/whl/cpu docker compose build
# and comment out the `deploy:` block under `app` in docker-compose.yml
docker compose up -d
```

The torch CUDA wheels bundle their own CUDA runtime, so there is **no CUDA
base image** and nothing CUDA-related to install inside the container — only
the host toolkit matters.

## Run without Docker

Needs **Python 3.10+** and a reachable PostgreSQL.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
set DATABASE_URL=postgresql://spring_qc:<password>@localhost:5432/spring_qc
python -m uvicorn app:app --host 0.0.0.0 --port 8001
```

On Windows, `setup.bat` then `run.bat` do the same (you still need the
`DATABASE_URL` env var and a running PostgreSQL — the easiest source is
`docker compose up -d db`).

## Using it

| URL | Who | What |
|-----|-----|------|
| `/admin` | Admin | Configure operators (name / machine no. / 4-digit PIN), assign an RTSP camera or a test video to an operator, confirm the ROI on the first frame, flip the assignment **Live** |
| `/operator` | Operator | Sign in (pick name + PIN), then decide each spring as it leaves the ROI |
| `/monitor` | Admin | Watch the live inference stream for any operator |
| `/reports` | Admin | Day-wise and per-operator dashboards, defect rate, recent inspections with images; light/dark toggle; **⬇ Export Excel** — filter by operator / period / result and download an `.xlsx` with the captured frames embedded per row |

Each operator gets their **own** ROI (saved per operator) and their **own**
continuously-incrementing S.No.

## Data model

One PostgreSQL database (`spring_qc`), three tables:

- **`operators`** — name, machine number, salted-hashed PIN, that operator's ROI polygon
- **`inspections`** — one row per decided spring: job id, operator, S.No, `started_at` + IN/OUT offsets (→ real clock times) / duration, verdict (`ok` / `defective` / `unknown`), `decided_at`
- **`assignments`** — one saved operator→source mapping (RTSP URL or uploaded video + a friendly name) so the admin's setup survives a restart

Captured spring frames stay on disk (`Output/defects/<job>/<s_no>/frame_N.jpg`);
only the count is in the DB. Uploaded test videos stay in `uploads/`.

## Key config knobs (`config.yaml` → also in admin **Settings**)

- `model.conf_threshold` / `model.iou_threshold` — detection sensitivity
- `tracking.tracker` — `bytetrack` (default), `botsort`, `ocsort`, `deepocsort`
- `tracking.confirm_frames` — a spring must be seen inside the ROI this many
  consecutive frames before it counts (filters out one-off misdetections)
- `tracking.out_frames` — consecutive frames outside the ROI before OUT fires
- `tracking.recover_frames` / `recover_dist` — ID recovery through occlusion
