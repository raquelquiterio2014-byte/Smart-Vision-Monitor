"""FastAPI evolution: events API, health check and real-time WebSocket."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from collections import deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
EVENT_FILE = BASE_DIR.parent / "data" / "events.jsonl"
app = FastAPI(title="Smart Vision Monitor API", version="0.2.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "smart-vision-monitor"}


def parse_event(line: str):
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return event if isinstance(event, dict) else None


@app.get("/api/events")
def events(limit: int = 100):
    if not EVENT_FILE.exists():
        return []
    recent = deque(maxlen=min(max(limit, 1), 500))
    with EVENT_FILE.open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                continue  # A writer may still be completing this record.
            event = parse_event(line)
            if event is not None:
                recent.append(event)
    return list(reversed(recent))


@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    await websocket.accept()
    position = EVENT_FILE.stat().st_size if EVENT_FILE.exists() else 0
    try:
        while True:
            if EVENT_FILE.exists():
                size = EVENT_FILE.stat().st_size
                if size < position:
                    position = 0
                if size > position:
                    with EVENT_FILE.open("rb") as stream:
                        stream.seek(position)
                        while True:
                            start = stream.tell()
                            line = stream.readline()
                            if not line:
                                break
                            if not line.endswith(b"\n"):
                                stream.seek(start)
                                break
                            event = parse_event(line)
                            if event is not None:
                                await websocket.send_json(event)
                        position = stream.tell()
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return

