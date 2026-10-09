# Smart Vision Monitor

Educational prototype that converts video into tracking events with temporary IDs. It detects only the `person` class, assigns temporary tracking IDs, evaluates motion, checks virtual zones, and writes JSONL events. It does **not** perform facial recognition or identity inference.

## Version 1 — desktop MVP

1. Install Python 3.11 or 3.12.
2. Open a terminal in this folder.
3. Create and activate a virtual environment.
4. Run `pip install -r requirements.txt`.
5. Run `python monitor.py`.

The YOLO weights download automatically on first execution. Use **Start webcam** or **Open video**. Edit `config.yaml` to adjust confidence, zones, motion threshold, model, or GPU use.

Events are stored in `data/events.jsonl`. Frames are not stored by default.

## Version 2 — FastAPI dashboard

Keep the desktop monitor running, then start the API in a second terminal:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The page loads event history and receives new events through WebSocket.

## Architecture

1. Camera/video capture and YOLO person detection.
2. ByteTrack tracking IDs, trajectory and virtual-zone rules.
3. JSONL event storage.
4. FastAPI REST/WebSocket and a local web dashboard.

## Technical evolution plan

### Phase 1 — validated local prototype

- Calibrate confidence, zones and motion thresholds with staged videos.
- Add unit tests for zone transitions, cooldown and malformed configuration.
- Measure false positives, missed detections, FPS and alert latency.

### Phase 2 — service separation

- Move capture/inference to a dedicated worker.
- Publish structured events to Redis Streams or MQTT instead of polling JSONL.
- Store events in PostgreSQL; define retention and deletion policies.
- Keep raw video local unless recording is explicitly required and authorized.

### Phase 3 — secure web monitoring

- Add authenticated users, roles, TLS, audit logs and session expiration.
- Create WebSocket channels per authorized camera/location.
- Add acknowledgement and resolution states to alerts.
- Never expose a public camera stream by default.

### Phase 4 — contextual intelligence

- Add temporal rules such as prolonged inactivity or occupancy limits.
- Train/evaluate context-specific models only with lawful, representative data.
- Include confidence, rule evidence and human review in each sensitive alert.
- Version models and rules; monitor drift and performance by environment.

## Safety and privacy boundaries

This software is an experimental educational aid, not a certified child-safety system. It must not replace responsible adult supervision or emergency procedures. Before real deployment, obtain appropriate consent and legal review, minimize collected data, encrypt data in transit and at rest, restrict access, define retention limits, test bias and failure modes, and conduct security and safety validation.


## Windows / PyCharm quick start

Extract the project, then open its folder in PyCharm. Select Python 3.11 or 3.12. Run these commands in the terminal from the project root:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m tkinter
python monitor.py
```

The Tkinter command should open a small test window; close it before launching the monitor. The desktop needs a display, webcam permission or a readable video file. Model dependencies can require significant disk space. Internet is required for installation and the initial model-weight download.

To open the web dashboard without installing the vision stack:

```bat
python -m pip install -r requirements-api.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Without events produced by the desktop, the history is empty. Keep both programs in the same extracted project folder.

## Checks performed on this revision

```bat
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Six automated tests passed locally: zone boundaries, health/dashboard routes, missing logs, malformed/incomplete records, history limits, and WebSocket delivery of a UTF-8 record written in two parts. Python syntax was checked separately. The checks run without downloading YOLO weights or opening a camera.

The desktop rejects starting another session while its worker is active and releases the capture in a finally block. After pressing Stop, wait for Stopped before starting again. The dashboard uses text nodes for event fields. The API skips malformed records and waits for complete WebSocket records instead of failing on a partial write.

### Owner-reported local validation

On October 9, 2026, Raquel Cruz confirmed successful local execution using a **video file**. This is owner-reported validation; no screenshots, runtime logs, metrics or tested commit identifier were supplied for this check. It does not establish that the newly published revision was rerun.

Webcam capture, GPU operation, a manual check of the FastAPI dashboard and a clean installation of the full vision stack remain unconfirmed. The automated checks above do not exercise actual YOLO/ByteTrack inference or the desktop layout.

## Current implementation limits

- There is no login or access control. Bind the API to 127.0.0.1 for local use; authentication is a future feature.
- Temporary tracking IDs do not guarantee anonymization; timestamps and location context can still be sensitive.
- Motion is displacement in pixels between processed frames, not physical speed or calibrated risk.
- ZONE_EXIT means an observed track center crossed out of a zone. Losing a detection does not establish that a person left.
- JSONL history is scanned on each REST request. The API assumes one local writer and does not provide database-level coordination or retention.
- The web dashboard displays the last 30 rows; its count is the number of events received during this page session, including the initial history, rather than a lifetime total.
- The WebSocket does not reconnect automatically after a disconnect.
- save_video, output_video, store_frames and app.source are reserved configuration fields and are not wired into the current desktop controls. No video/frame recording is implemented; Start webcam uses camera 0 and Open video uses the selected file.
- The backend reads data/events.jsonl at the project root. Keep monitoring.event_log at that default when using the dashboard.

No credentials were found in the supplied source/configuration files. The .gitignore excludes local environments, model weights, recordings and generated event logs from normal Git staging. No license was added; the project owner should select one before describing the code as licensed open source.
