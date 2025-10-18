from __future__ import annotations

import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Deque, Dict, List

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..config import LoopConfig, DEFAULT_CONFIG
from ..core.models import ExecutionEvent, LoopSnapshot


def _snapshot_to_dict(snapshot: LoopSnapshot) -> Dict:
    payload = asdict(snapshot)
    # dataclasses.asdict converts datetimes to iso automatically when str() is called by FastAPI response
    return payload


@dataclass
class DashboardServer:
    """FastAPI-based dashboard backend for real-time monitoring."""

    config: LoopConfig = DEFAULT_CONFIG
    buffer_size: int = 512
    app: FastAPI = field(init=False)
    _snapshots: Deque[Dict] = field(init=False)
    _timeline: Deque[Dict] = field(init=False)
    _events: Deque[Dict] = field(init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def __post_init__(self):
        self._snapshots = deque(maxlen=self.buffer_size)
        self._timeline = deque(maxlen=self.buffer_size)
        self._events = deque(maxlen=self.buffer_size)
        self.app = FastAPI(title="yamada7 dashboard", version="0.1.0")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._register_routes()

    def _register_routes(self):
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.exists():
            self.app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")

        @self.app.get("/")
        def root():
            if static_dir.exists():
                return RedirectResponse(url="/ui/index.html", status_code=302)
            return {"message": "Dashboard UI is not bundled. Access /snapshots or /metrics."}

        @self.app.get("/health")
        def health():
            return {"status": "ok", "buffer": len(self._snapshots)}

        @self.app.get("/snapshots")
        def snapshots(limit: int = 50):
            limit = max(1, min(limit, self.buffer_size))
            items = list(self._snapshots)[-limit:]
            return {"items": items}

        @self.app.get("/metrics")
        def metrics(limit: int = 200):
            limit = max(1, min(limit, self.buffer_size))
            items = list(self._timeline)[-limit:]
            return {"items": items}

        @self.app.get("/events")
        def events(limit: int = 200):
            limit = max(1, min(limit, self.buffer_size))
            items = list(self._events)[-limit:]
            return {"items": items}

        @self.app.get("/latest")
        def latest():
            if not self._snapshots:
                return {"item": None}
            return {"item": self._snapshots[-1]}

    def publisher(self) -> callable:
        def _inner(snapshot: LoopSnapshot):
            self._snapshots.append(_snapshot_to_dict(snapshot))
            self._timeline.append(self._extract_metrics(snapshot))
            for event in snapshot.events:
                self._events.append(_event_to_dict(event))

        return _inner

    def run_in_thread(self):
        if self._thread and self._thread.is_alive():
            return

        def _target():
            config = uvicorn.Config(
                self.app,
                host=self.config.dashboard_host,
                port=self.config.dashboard_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            server.run()

        self._thread = threading.Thread(target=_target, daemon=True)
        self._thread.start()

    @staticmethod
    def _extract_metrics(snapshot: LoopSnapshot) -> Dict:
        obs = snapshot.observation.data
        reward_total = snapshot.reward.external_reward + snapshot.reward.internal_reward
        return {
            "tick": snapshot.tick,
            "life": obs.get("life"),
            "resources": obs.get("resources"),
            "danger": obs.get("danger"),
            "unknown": obs.get("unknown"),
            "reward": reward_total,
            "external_reward": snapshot.reward.external_reward,
            "internal_reward": snapshot.reward.internal_reward,
            "fear_note": snapshot.reflection.fear_updates[-1] if snapshot.reflection.fear_updates else "",
            "curiosity_note": snapshot.reflection.curiosity_updates[-1] if snapshot.reflection.curiosity_updates else "",
        }


def _event_to_dict(event: ExecutionEvent) -> Dict:
    return {
        "timestamp": event.timestamp.isoformat(),
        "channel": event.channel.value,
        "payload": event.payload,
    }
