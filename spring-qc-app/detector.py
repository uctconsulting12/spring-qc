import cv2
import numpy as np
from pathlib import Path


def resolve_device(device):
    """Resolve a config device value to a concrete inference device string."""
    if device is None or str(device).lower() in ('auto', ''):
        try:
            import torch
            return 'cuda' if torch.cuda.is_available() else 'cpu'
        except Exception:
            return 'cpu'
    return str(device)


def point_in_polygon(point, polygon):
    if polygon is None or len(polygon) < 3:
        return False
    return cv2.pointPolygonTest(np.array(polygon, dtype=np.int32), point, False) >= 0


def draw_roi(frame, window_name, existing_roi=None):
    roi_points = list(existing_roi) if existing_roi else []
    drawing = False

    def mouse_callback(event, x, y, flags, param):
        nonlocal roi_points, drawing
        if event == cv2.EVENT_LBUTTONDOWN:
            roi_points.append((x, y))
            drawing = True
        elif event == cv2.EVENT_RBUTTONDOWN and len(roi_points) > 0:
            roi_points.pop()

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, mouse_callback)

    mode = "EDIT" if existing_roi else "DRAW"
    print(f"\n=== {mode} ROI POLYGON ===")
    print("Left-click: Add point")
    print("Right-click: Remove last point")
    print("Press 'ENTER' to confirm ROI")
    print("Press 'c' to clear all points")
    print("Press 'ESC' to cancel")
    if existing_roi:
        print("Press 'r' to reset to original ROI")

    while True:
        display = frame.copy()

        # Draw existing ROI as reference if editing
        if existing_roi and len(existing_roi) >= 3:
            cv2.polylines(display, [np.array(existing_roi, dtype=np.int32)],
                         True, (255, 0, 0), 1)
            cv2.putText(display, "Original ROI (blue)", (30, 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        if len(roi_points) > 0:
            for i, pt in enumerate(roi_points):
                cv2.circle(display, pt, 5, (0, 255, 0), -1)
                cv2.putText(display, str(i), (pt[0]+10, pt[1]-10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            if len(roi_points) > 1:
                cv2.polylines(display, [np.array(roi_points, dtype=np.int32)],
                             False, (0, 255, 255), 2)

            if len(roi_points) >= 3:
                cv2.polylines(display, [np.array(roi_points, dtype=np.int32)],
                             True, (0, 255, 0), 2)
                overlay = display.copy()
                cv2.fillPoly(overlay, [np.array(roi_points, dtype=np.int32)], (0, 255, 0))
                cv2.addWeighted(overlay, 0.15, display, 0.85, 0, display)

        cv2.putText(display, f"{mode} ROI Polygon - ENTER to confirm, ESC to cancel", (30, 50),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        cv2.imshow(window_name, display)
        key = cv2.waitKey(1) & 0xFF

        if key == 13:  # ENTER
            if len(roi_points) >= 3:
                print(f"ROI confirmed with {len(roi_points)} points")
                return roi_points
            else:
                print("Need at least 3 points for a polygon!")
        elif key == 27:  # ESC
            if existing_roi:
                print("Using original ROI")
                return existing_roi
            print("ROI cancelled")
            return None
        elif key == ord('c'):
            roi_points = []
            print("Cleared all points")
        elif key == ord('r') and existing_roi:
            roi_points = list(existing_roi)
            print("Reset to original ROI")

    cv2.destroyWindow(window_name)
    return None


def show_roi_options(frame, window_name, existing_roi):
    """Show existing ROI and let user choose action"""
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    while True:
        display = frame.copy()

        # Draw existing ROI
        if existing_roi and len(existing_roi) >= 3:
            cv2.polylines(display, [np.array(existing_roi, dtype=np.int32)],
                         True, (0, 255, 255), 3)
            overlay = display.copy()
            cv2.fillPoly(overlay, [np.array(existing_roi, dtype=np.int32)], (0, 255, 0))
            cv2.addWeighted(overlay, 0.15, display, 0.85, 0, display)
            cv2.putText(display, f"Existing ROI ({len(existing_roi)} points)", (30, 50),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        cv2.putText(display, "Options:", (30, 120),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(display, "  [1] Use existing ROI", (50, 170),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(display, "  [2] Edit existing ROI", (50, 210),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
        cv2.putText(display, "  [3] Clear ROI (draw new)", (50, 250),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
        cv2.putText(display, "  [ESC] Skip ROI", (50, 290),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imshow(window_name, display)
        key = cv2.waitKey(0) & 0xFF

        if key == ord('1'):
            print("Using existing ROI")
            return 'use', existing_roi
        elif key == ord('2'):
            print("Editing existing ROI...")
            cv2.destroyWindow(window_name)
            edited_roi = draw_roi(frame, window_name, existing_roi)
            return 'edit', edited_roi
        elif key == ord('3'):
            print("Clearing ROI - draw new one...")
            cv2.destroyWindow(window_name)
            new_roi = draw_roi(frame, window_name, None)
            return 'new', new_roi
        elif key == 27:  # ESC
            print("Skipping ROI")
            return 'skip', None


def get_roi_from_config(config):
    if 'roi' in config and 'points' in config['roi']:
        # Convert lists back to tuples for consistency
        return [tuple(pt) for pt in config['roi']['points']]
    return None


class SpringDetector:
    """Core spring detection loop with tracking + ROI in/out events.

    Streams annotated frames and events via callbacks, and optionally writes
    to a video writer.

    Callbacks:
        on_frame(annotated_frame_bgr)   -> called for every annotated frame
        on_event(event: dict)           -> called on enter/exit/still-in events
    """

    def __init__(self, model, model_config, track_config, event_config,
                 roi_points, on_frame=None, on_event=None, start_serial=1):
        self.model = model
        self.model_config = model_config
        self.track_config = track_config or {}
        self.event_config = event_config or {}
        self.roi_points = [tuple(p) for p in roi_points] if roi_points else roi_points
        self.on_frame = on_frame
        self.on_event = on_event

        self.device = resolve_device(model_config.get('device', 'auto'))
        self.tracking_enabled = self.track_config.get('enabled', True)

        self.spring_events = []
        self.track_serial = {}
        self.next_serial = max(1, int(start_serial))
        self.unique_tracks = set()
        self.live = {}  # s_no -> elapsed seconds currently inside ROI

        # A track must be detected inside the ROI for this many *consecutive*
        # frames before it's confirmed as a real entry (S.No assigned, 'enter'
        # event fired) - one stray misdetected frame no longer spawns a
        # phantom spring. Mirrors out_frames, but for the entry side.
        self.confirm_frames = int(self.track_config.get('confirm_frames', 100))

        # ID-recovery state (persist identity across occlusion / detection loss)
        self._lost = {}       # track_id -> {center, cls, lost_frame, in_roi}
        self._last_frame_ids = set()

        self.spring_in_count = 0
        self.spring_out_count = 0
        self.no_detection_count = 0

        # Defect-capture state: last N bbox crops per active track, and pending
        # OUT records (by S.No) awaiting a defective/not-defective answer.
        defect_cfg = self.event_config.get('defect', {})
        self.defect_enabled = defect_cfg.get('enabled', True)
        self.defect_num_frames = int(defect_cfg.get('num_frames', 5))
        self.defect_max_side = int(defect_cfg.get('max_side', 256))
        self._bbox_cache = {}   # track_id -> deque of JPEG bytes (recent crops)
        self._pending = {}      # s_no -> record awaiting defect answer

    def set_roi(self, roi_points):
        """Swap the active ROI polygon while the detector is running. The frame
        loop re-reads self.roi_points every iteration, so a live stream picks
        this up on its next frame - no restart needed."""
        self.roi_points = [tuple(p) for p in roi_points] if roi_points else roi_points

    def _resolve_tracker(self, tracker):
        """Resolve tracker name/path, preferring the tuned low-compute bytetrack config."""
        name = str(tracker).lower().strip()
        # Use our tuned ByteTrack config for low compute + long ID retention
        if name in ('bytetrack', 'bytetrack.yaml'):
            bundled = Path(__file__).resolve().parent / 'trackers' / 'bytetrack_spring.yaml'
            return str(bundled) if bundled.exists() else 'bytetrack.yaml'
        # user-friendly -> built-in ultralytics tracker yaml
        alias = {
            'deepsort': 'deepocsort.yaml',
            'botsort': 'botsort.yaml',
            'ocsort': 'ocsort.yaml',
            'deepocsort': 'deepocsort.yaml',
        }
        if name in alias:
            return alias[name]
        # Otherwise treat as a direct yaml name or path
        return name

    def _recover_id(self, center, cls_id, active_ids):
        """Try to restore a lost track ID for a detection near a recently-lost track.

        Returns the recovered track_id or None. This keeps a spring's ID stable
        after occlusion / detection loss when the light tracker dropped it.
        """
        best_id = None
        best_dist = float('inf')
        for tid, info in self._lost.items():
            if tid in active_ids:
                continue
            if info['cls'] != cls_id:
                continue
            dx = center[0] - info['center'][0]
            dy = center[1] - info['center'][1]
            d = dx * dx + dy * dy
            if d < best_dist:
                best_dist = d
                best_id = tid
        # best_dist is squared; compare against squared threshold
        dist_px = int(self.track_config.get('recover_dist', 120))
        if best_dist <= dist_px * dist_px:
            return best_id
        return None

    def _buffer_crop(self, frame, xyxy, track_id):
        """Capture a scaled JPEG crop of the spring's bbox into the recent-frames
        buffer for this track (kept during its in-ROI duration)."""
        import cv2
        if not self.defect_enabled:
            return
        h, w = frame.shape[:2]
        x1 = max(0, int(xyxy[0])); y1 = max(0, int(xyxy[1]))
        x2 = min(w, int(xyxy[2])); y2 = min(h, int(xyxy[3]))
        if x2 <= x1 or y2 <= y1:
            return
        crop = frame[y1:y2, x1:x2]
        # Scale down long side to keep payloads small
        ch, cw = crop.shape[:2]
        longest = max(ch, cw)
        if longest > self.defect_max_side:
            scale = self.defect_max_side / longest
            crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)),
                              interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode('.jpg', crop)
        if not ok:
            return
        dq = self._bbox_cache.setdefault(track_id, __import__('collections').deque(maxlen=self.defect_num_frames))
        dq.append(jpg.tobytes())

    def _finalize_out(self, s_no, track_id, in_frame, out_frame, fps, class_id=None):
        """Build a pending defect record for an OUT spring, including its buffered
        bbox frames as base64. Stored so /save-defect can persist it server-side."""
        import base64
        frames = [base64.b64encode(b).decode('ascii') for b in self._bbox_cache.get(track_id, [])]
        duration_frames = max(0, out_frame - in_frame)
        rec = {
            's_no': int(s_no),
            'track_id': int(track_id) if track_id is not None else None,
            'in_frame': int(in_frame),
            'out_frame': int(out_frame),
            'duration_frames': int(duration_frames),
            'in_time_sec': round(in_frame / fps, 3) if fps > 0 else 0,
            'out_time_sec': round(out_frame / fps, 3) if fps > 0 else 0,
            'duration_sec': round(duration_frames / fps, 3) if fps > 0 else 0,
            'class_id': int(class_id) if class_id is not None else -1,
            'frames_b64': frames,
            'defect': None,
        }
        self._pending[int(s_no)] = rec
        return rec

    def run(self, video_source, max_frames=None, writer=None, should_stop=None):
        """Run detection over a video file path or RTSP URL.

        Args:
            video_source: str path or URL, or open source accepted by cv2.VideoCapture
            max_frames: optional frame limit (None for unlimited)
            writer: optional cv2.VideoWriter to record annotated frames
            should_stop: optional callable returning True to stop processing early
        """
        cap = cv2.VideoCapture(str(video_source))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {video_source}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        events_enabled = self.event_config.get('enabled', True)
        roi_points = self.roi_points  # re-read each frame in the loop so live ROI edits apply

        # Reset ID-recovery per run
        self._lost = {}
        self._last_frame_ids = set()
        self._bbox_cache = {}
        self._pending = {}
        recover_frames = int(self.track_config.get('recover_frames', 90))  # frames to keep a lost ID recoverable
        recover_dist = int(self.track_config.get('recover_dist', 120))     # px nearest center to restore ID

        # Tracking / event state
        track_history = {}
        track_in_roi = {}
        track_class = {}
        track_currently_in = {}
        track_first_in_frame = {}
        detected_track_ids = set()
        # Per-ID "OUT" after N consecutive frames not detected inside ROI
        out_frames = int(self.track_config.get('out_frames', 90))
        track_gap_start = {}   # track_id -> frame when this ID last left the ROI
        inside_frame_ids = set()  # track_ids detected inside ROI this frame
        confirm_frames = self.confirm_frames
        track_pending_count = {}  # track_id -> consecutive in-ROI frames, not yet confirmed

        spring_events = self.spring_events
        track_serial = self.track_serial

        frame_count = 0
        max_history = self.track_config.get('max_history', 30)
        classes = self.model_config.get('classes', None)

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                roi_points = self.roi_points  # pick up any live ROI edit

                if self.tracking_enabled:
                    tracker_cfg = self._resolve_tracker(self.track_config.get('tracker', 'bytetrack.yaml'))
                    results = self.model.track(
                        source=frame,
                        conf=self.model_config['conf_threshold'],
                        iou=self.model_config['iou_threshold'],
                        device=self.device,
                        verbose=False,
                        persist=self.track_config.get('persist', True),
                        tracker=tracker_cfg,
                        classes=classes
                    )
                else:
                    results = self.model.predict(
                        source=frame,
                        conf=self.model_config['conf_threshold'],
                        iou=self.model_config['iou_threshold'],
                        device=self.device,
                        verbose=False
                    )

                annotated_frame = results[0].plot()

                # Draw ROI on frame (single clean polygon: light tinted fill + solid outline)
                if roi_points is not None and len(roi_points) >= 3:
                    roi_np = np.array(roi_points, dtype=np.int32)
                    overlay = annotated_frame.copy()
                    cv2.fillPoly(overlay, [roi_np], (0, 255, 255))
                    cv2.addWeighted(overlay, 0.08, annotated_frame, 0.92, 0, annotated_frame)
                    cv2.polylines(annotated_frame, [roi_np], True, (0, 255, 255), 2)
                    cv2.putText(annotated_frame, "ROI",
                               (roi_points[0][0], roi_points[0][1] - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

                detections = results[0].boxes
                frame_status = "NO SPRING DETECTED"
                status_color = (0, 0, 255)
                detected_track_ids = set()
                inside_frame_ids = set()

                if detections is not None and len(detections) > 0:
                    track_ids = detections.id
                    if track_ids is not None:
                        track_ids = track_ids.cpu().numpy().astype(int)
                    else:
                        track_ids = [None] * len(detections)

                    for i, box in enumerate(detections):
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        xyxy = box.xyxy[0].cpu().numpy()
                        track_id = track_ids[i] if i < len(track_ids) else None

                        center_x = int((xyxy[0] + xyxy[2]) / 2)
                        center_y = int((xyxy[1] + xyxy[3]) / 2)
                        center = (center_x, center_y)

                        # ID recovery: if the light tracker produced no id, or a brand-new
                        # id that is spatially near a recently-lost track of the same class,
                        # restore the old id so the spring keeps a consistent identity
                        # through occlusion / detection loss.
                        proposed = track_id
                        if self.tracking_enabled:
                            if (proposed is None) or (proposed not in track_history):
                                recovered = self._recover_id(center, cls_id, set(track_ids) | set(track_history.keys()))
                                if recovered is not None:
                                    proposed = recovered
                        else:
                            # tracking off -> use our own recovery to keep stable ids
                            recovered = self._recover_id(center, cls_id, set())
                            if recovered is None:
                                # no lost match and no tracker: assign a fresh transient id from center
                                # (keeps unique identity per detection stream)
                                proposed = None
                            else:
                                proposed = recovered

                        track_id = proposed
                        if track_id is not None:
                            self._lost.pop(track_id, None)

                        if track_id is not None:
                            self.unique_tracks.add(track_id)
                            detected_track_ids.add(track_id)
                            if track_id not in track_history:
                                track_history[track_id] = []
                            track_history[track_id].append(center)
                            track_class[track_id] = cls_id
                            if len(track_history[track_id]) > max_history:
                                track_history[track_id] = track_history[track_id][-max_history:]

                        is_inside = point_in_polygon(center, roi_points) if roi_points else False

                        # Update track ROI state
                        if is_inside and track_id is not None:
                            inside_frame_ids.add(track_id)
                            track_gap_start.pop(track_id, None)  # spring present in ROI -> reset gap
                            track_in_roi[track_id] = is_inside
                            if self.defect_enabled:
                                self._buffer_crop(frame, xyxy, track_id)

                        if is_inside:
                            self.spring_in_count += 1
                            frame_status = f"SPRING: IN (conf: {conf:.2f})"
                            status_color = (0, 255, 0)
                        else:
                            self.spring_out_count += 1
                            frame_status = f"SPRING: OUT (conf: {conf:.2f})"
                            status_color = (0, 0, 255)

                        # Draw center point
                        cv2.circle(annotated_frame, center, 8, status_color, -1)
                        cv2.putText(annotated_frame, "CENTER", (center_x + 15, center_y),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 2)

                        # Draw Serial Number (hide internal track ID) - only when inside ROI
                        if track_id is not None and is_inside:
                            s_no = track_serial.get(track_id, '?')
                            elapsed = 0.0
                            if s_no in self.live:
                                elapsed = self.live[s_no]
                            cv2.putText(annotated_frame, f"S.No: {s_no}  ({elapsed:.1f}s)",
                                       (int(xyxy[0]), int(xyxy[1]) - 10),
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

                            # Draw trajectory
                            if track_id in track_history and len(track_history[track_id]) > 1:
                                pts = np.array(track_history[track_id], dtype=np.int32)
                                cv2.polylines(annotated_frame, [pts], False, (255, 255, 0), 2)
                else:
                    self.no_detection_count += 1

                # Per-ID entry confirmation: a track must be detected inside the
                # ROI for `confirm_frames` *consecutive* frames before it is
                # confirmed as a real spring - S.No assigned and 'enter' fired
                # only then. A single misdetected frame (or a few) never gets
                # this far, since any frame the track isn't seen inside the
                # ROI resets its pending count back to zero below.
                if events_enabled and roi_points is not None:
                    for track_id in inside_frame_ids:
                        if track_currently_in.get(track_id, False):
                            continue  # already confirmed - handled by the OUT pass
                        track_pending_count[track_id] = track_pending_count.get(track_id, 0) + 1
                        if track_pending_count[track_id] < confirm_frames:
                            continue
                        # Confirmed: back-date the entry to when it first
                        # appeared, not to this (later) confirmation frame.
                        in_frame = frame_count - confirm_frames + 1
                        track_currently_in[track_id] = True
                        track_first_in_frame[track_id] = in_frame
                        track_pending_count.pop(track_id, None)
                        if track_id not in track_serial:
                            track_serial[track_id] = self.next_serial
                            self.next_serial += 1
                        track_gap_start.pop(track_id, None)
                        in_time_sec = in_frame / fps if fps > 0 else 0
                        print(f"[EVENT] Spring S.No {track_serial[track_id]} ENTERED ROI at frame {in_frame} ({in_time_sec:.2f}s) "
                              f"[confirmed after {confirm_frames} frames]")
                        if self.on_event is not None:
                            self.on_event({
                                'type': 'enter',
                                's_no': track_serial[track_id],
                                'in_frame': in_frame,
                                'in_time_sec': round(in_time_sec, 3),
                                'class_id': track_class.get(track_id, -1),
                            })

                    # Any track that was pending but wasn't seen inside the ROI
                    # this frame breaks its consecutive-frame streak - discard
                    # it as a likely misdetection rather than resuming later.
                    for track_id in list(track_pending_count.keys()):
                        if track_id not in inside_frame_ids:
                            track_pending_count.pop(track_id, None)

                # Per-ID OUT: a spring that entered the ROI is declared out when this
                # specific ID has not been detected inside the ROI for `out_frames`
                # consecutive frames (occlusion, moved out, or detection loss).
                if events_enabled and roi_points is not None:
                    for track_id in list(track_currently_in.keys()):
                        if not track_currently_in[track_id]:
                            continue
                        if track_id in inside_frame_ids:
                            continue  # still present in ROI -> gap resets
                        # start the gap on the first frame this ID is not inside ROI
                        gap_start = track_gap_start.setdefault(track_id, frame_count)
                        if frame_count - gap_start >= out_frames:
                            # Declare OUT at the first frame the spring left the ROI
                            track_currently_in[track_id] = False
                            track_gap_start.pop(track_id, None)
                            in_frame = track_first_in_frame.get(track_id, frame_count)
                            out_frame = gap_start
                            duration_frames = max(0, out_frame - in_frame)
                            duration_sec = duration_frames / fps if fps > 0 else 0
                            in_time_sec = in_frame / fps if fps > 0 else 0
                            out_time_sec = out_frame / fps if fps > 0 else 0
                            s_no = track_serial.get(track_id, 0)
                            rec = self._finalize_out(s_no, track_id, in_frame, out_frame, fps, class_id=track_class.get(track_id, -1))
                            event = {
                                's_no': rec['s_no'],
                                'track_id': rec['track_id'],
                                'in_frame': rec['in_frame'],
                                'out_frame': rec['out_frame'],
                                'in_time_sec': rec['in_time_sec'],
                                'out_time_sec': rec['out_time_sec'],
                                'duration_frames': rec['duration_frames'],
                                'duration_sec': rec['duration_sec'],
                                'class_id': rec['class_id'],
                                'frames_b64': rec['frames_b64'],
                            }
                            spring_events.append(event)
                            print(f"[EVENT] Spring S.No {rec['s_no']} OUT (not in ROI for {out_frames} frames) at frame {in_frame} ({event['out_time_sec']:.2f}s) | Duration: {event['duration_sec']:.2f}s")
                            if self.on_event is not None:
                                self.on_event({**event, 'type': 'exit'})

                # Build live in-ROI timing map for dashboard (s_no -> elapsed seconds)
                self.live = {}
                if events_enabled and roi_points is not None:
                    for track_id, is_in in track_currently_in.items():
                        if is_in:
                            in_frame = track_first_in_frame.get(track_id, frame_count)
                            elapsed = (frame_count - in_frame) / fps if fps > 0 else 0
                            self.live[track_serial.get(track_id, 0)] = round(elapsed, 3)

                # Track identity through occlusion: mark IDs seen last frame but not
                # detected now as "lost" so they can be recovered when the spring reappears.
                for tid in list(self._last_frame_ids):
                    if tid not in detected_track_ids and track_history.get(tid):
                        if tid not in self._lost:
                            self._lost[tid] = {
                                'center': track_history[tid][-1],
                                'cls': track_class.get(tid, -1),
                                'lost_frame': frame_count,
                            }
                self._last_frame_ids = set(detected_track_ids)
                # Prune lost tracks older than the recovery window
                for tid in list(self._lost.keys()):
                    if frame_count - self._lost[tid]['lost_frame'] > recover_frames:
                        del self._lost[tid]

                # Draw status
                cv2.putText(annotated_frame, frame_status, (30, 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.2, status_color, 3)
                cv2.putText(annotated_frame, f"Frame: {frame_count}/{total_frames}", (30, 100),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.putText(annotated_frame, f"Unique Tracks: {len(self.unique_tracks)}", (30, 140),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
                cv2.putText(annotated_frame, "IN = Green  |  OUT = Red  |  S.No = Yellow", (30, height - 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                if writer is not None:
                    writer.write(annotated_frame)

                if self.on_frame is not None:
                    self.on_frame(annotated_frame)

                frame_count += 1
                if max_frames is not None and frame_count >= max_frames:
                    break
                if should_stop is not None and should_stop():
                    break
        finally:
            # Handle springs still in ROI at end of source
            if events_enabled and roi_points is not None:
                for track_id, is_in in track_currently_in.items():
                    if is_in:
                        in_frame = track_first_in_frame.get(track_id, frame_count)
                        out_frame = frame_count
                        duration_frames = out_frame - in_frame
                        duration_sec = duration_frames / fps if fps > 0 else 0
                        in_time_sec = in_frame / fps if fps > 0 else 0
                        out_time_sec = out_frame / fps if fps > 0 else 0

                        s_no = track_serial.get(track_id, 0)
                        rec = self._finalize_out(s_no, track_id, in_frame, out_frame, fps, class_id=track_class.get(track_id, -1))
                        event = {
                            's_no': rec['s_no'],
                            'track_id': rec['track_id'],
                            'in_frame': rec['in_frame'],
                            'out_frame': rec['out_frame'],
                            'in_time_sec': rec['in_time_sec'],
                            'out_time_sec': rec['out_time_sec'],
                            'duration_frames': rec['duration_frames'],
                            'duration_sec': rec['duration_sec'],
                            'class_id': rec['class_id'],
                            'frames_b64': rec['frames_b64'],
                        }
                        spring_events.append(event)
                        print(f"[EVENT] Spring S.No {s_no} STILL IN ROI at video end (frame {frame_count}) | Duration so far: {duration_sec:.2f}s")
                        if self.on_event is not None:
                            self.on_event({**event, 'type': 'still_in'})

            cap.release()

        return {
            'frame_count': frame_count,
            'spring_in_count': self.spring_in_count,
            'spring_out_count': self.spring_out_count,
            'no_detection_count': self.no_detection_count,
            'unique_tracks': len(self.unique_tracks),
            'events': spring_events,
            'fps': fps if fps > 0 else 0,
        }
