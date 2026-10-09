"""Privacy-first educational people monitoring prototype."""
from __future__ import annotations

import argparse
import json
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any

import cv2
import tkinter as tk
import yaml
from tkinter import filedialog, messagebox, ttk
from ultralytics import YOLO
from vision_rules import inside


@dataclass(frozen=True)
class Event:
    timestamp: str
    type: str
    track_id: int
    zone: str | None = None
    value: float | None = None


class EventStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write(self, event: Event) -> None:
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")


class VisionEngine:
    def __init__(self, config: dict[str, Any], event_queue: Queue) -> None:
        self.config = config
        self.event_queue = event_queue
        self.store = EventStore(config["monitoring"]["event_log"])
        self.model = YOLO(config["model"]["weights"])
        self.trails: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=int(config["monitoring"]["trail_length"]))
        )
        self.zones_by_track: dict[int, set[str]] = defaultdict(set)
        self.last_motion_alert: dict[int, float] = defaultdict(float)

    def emit(self, event_type: str, track_id: int, zone: str | None = None,
             value: float | None = None) -> None:
        event = Event(datetime.now(timezone.utc).isoformat(), event_type, track_id, zone, value)
        self.store.write(event)
        self.event_queue.put(event)

    inside = staticmethod(inside)

    def process(self, frame):
        height, width = frame.shape[:2]
        model_cfg = self.config["model"]
        result = self.model.track(
            frame,
            persist=True,
            classes=[0],
            conf=float(model_cfg["confidence"]),
            tracker=model_cfg["tracker"],
            device=model_cfg["device"],
            verbose=False,
        )[0]

        zones: list[tuple[str, tuple[int, int, int, int], tuple[int, int, int]]] = []
        for zone in self.config["zones"]:
            nx1, ny1, nx2, ny2 = zone["rect"]
            rect = (int(nx1 * width), int(ny1 * height), int(nx2 * width), int(ny2 * height))
            color = tuple(zone["color"])
            zones.append((zone["name"], rect, color))
            cv2.rectangle(frame, rect[:2], rect[2:], color, 2)
            cv2.putText(frame, zone["name"], (rect[0], max(20, rect[1] - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        if result.boxes.id is None:
            return frame, 0

        boxes = result.boxes.xyxy.cpu().numpy().astype(int)
        ids = result.boxes.id.cpu().numpy().astype(int)
        now = time.monotonic()
        for (x1, y1, x2, y2), track_id in zip(boxes, ids):
            center = ((x1 + x2) // 2, (y1 + y2) // 2)
            trail = self.trails[track_id]
            motion = math.dist(trail[-1], center) if trail else 0.0
            trail.append(center)

            current_zones = {name for name, rect, _ in zones if self.inside(center, rect)}
            previous_zones = self.zones_by_track[track_id]
            for name in current_zones - previous_zones:
                self.emit("ZONE_ENTER", track_id, name)
            for name in previous_zones - current_zones:
                self.emit("ZONE_EXIT", track_id, name)
            self.zones_by_track[track_id] = current_zones

            limit = float(self.config["monitoring"]["high_motion_pixels"])
            cooldown = float(self.config["monitoring"]["high_motion_cooldown_seconds"])
            if motion > limit and now - self.last_motion_alert[track_id] >= cooldown:
                self.emit("HIGH_MOTION", track_id, value=round(motion, 1))
                self.last_motion_alert[track_id] = now

            color = (0, 165, 255) if motion > limit else (60, 220, 120)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"ID {track_id} | motion {motion:.0f}", (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            for p1, p2 in zip(list(trail), list(trail)[1:]):
                cv2.line(frame, p1, p2, color, 2)
        return frame, len(ids)


class DesktopApp:
    def __init__(self, root: tk.Tk, config: dict[str, Any]) -> None:
        self.root, self.config = root, config
        self.queue: Queue = Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        root.title(config["app"]["name"])
        root.geometry("1000x700")

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Button(top, text="Start webcam", command=lambda: self.start(0)).pack(side="left", padx=4)
        ttk.Button(top, text="Open video", command=self.open_video).pack(side="left", padx=4)
        ttk.Button(top, text="Stop", command=self.stop).pack(side="left", padx=4)
        self.status = ttk.Label(top, text="Ready")
        self.status.pack(side="right")
        self.video = ttk.Label(root, anchor="center")
        self.video.pack(fill="both", expand=True, padx=10)
        self.events = tk.Listbox(root, height=7)
        self.events.pack(fill="x", padx=10, pady=10)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_events()

    def open_video(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.avi *.mov *.mkv")])
        if path:
            self.start(path)

    def start(self, source: int | str) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.status.configure(text="Stop the current session and wait before restarting.")
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self.run, args=(source,), daemon=True)
        self.worker.start()

    def run(self, source: int | str) -> None:
        capture = None
        try:
            engine = VisionEngine(self.config, self.queue)
            capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                raise RuntimeError("Could not open the selected video source.")
            previous = time.perf_counter()
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    break
                frame, count = engine.process(frame)
                current = time.perf_counter()
                fps = 1 / max(current - previous, 1e-6)
                previous = current
                cv2.putText(frame, f"People: {count} | FPS: {fps:.1f}", (15, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                max_width = int(self.config["app"]["display_width"])
                if rgb.shape[1] > max_width:
                    scale = max_width / rgb.shape[1]
                    rgb = cv2.resize(rgb, None, fx=scale, fy=scale)
                ok, encoded = cv2.imencode(".ppm", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                if ok:
                    self.queue.put(("FRAME", encoded.tobytes(), count, fps))
        except Exception as exc:
            self.queue.put(("ERROR", str(exc)))
        finally:
            if capture is not None:
                capture.release()
            self.queue.put(("STOPPED",))

    def poll_events(self) -> None:
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if isinstance(item, Event):
                self.events.insert(0, f"{item.timestamp[11:19]}  {item.type}  ID {item.track_id}  {item.zone or ''}")
                self.events.delete(100, tk.END)
            elif item[0] == "FRAME":
                image = tk.PhotoImage(data=item[1])
                self.video.configure(image=image)
                self.video.image = image
                self.status.configure(text=f"Monitoring | {item[2]} people | {item[3]:.1f} FPS")
            elif item[0] == "ERROR":
                messagebox.showerror("Monitoring error", item[1])
            elif item[0] == "STOPPED":
                self.status.configure(text="Stopped")
        self.root.after(40, self.poll_events)

    def stop(self) -> None:
        self.stop_event.set()

    def close(self) -> None:
        self.stop()
        self.root.destroy()


def load_config(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    window = tk.Tk()
    DesktopApp(window, load_config(args.config))
    window.mainloop()

