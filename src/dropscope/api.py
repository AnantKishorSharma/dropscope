"""FastAPI app: REST + WebSocket over the drop-attribution pipeline.

`create_app` is intentionally free of background tasks so it is trivially
testable. The live feed + broadcast ticker are wired in `demo.py`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .aggregate import Aggregator
from .correlate import Correlator
from .models import DropEvent
from .registry import JobRegistry

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class Pipeline:
    """Glue: correlate -> aggregate -> broadcast, plus WebSocket fan-out."""

    def __init__(self, registry: JobRegistry, window_seconds: int = 120):
        self.registry = registry
        self.correlator = Correlator(registry)
        self.aggregator = Aggregator(window_seconds=window_seconds)
        self.subscribers: Set[asyncio.Queue] = set()
        self.recent = deque(maxlen=200)

    def ingest(self, event: DropEvent):
        ad = self.correlator.attribute(event)
        self.aggregator.ingest(ad)
        flat = ad.flat()
        self.recent.append(flat)
        self._broadcast({"type": "drop", "data": flat})
        return ad

    def _broadcast(self, msg: dict) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow client: drop the message rather than block

    def snapshot(self) -> dict:
        s = self.aggregator.summary()
        s["job_names"] = self.registry.names()
        for row in s["top_jobs"]:
            row["name"] = self.registry.name_of(row["job_id"]) or row["job_id"]
        return s


def create_app(registry: JobRegistry, window_seconds: int = 120, lifespan=None) -> FastAPI:
    app = FastAPI(title="dropscope", version="0.1.0", lifespan=lifespan)
    pipeline = Pipeline(registry, window_seconds=window_seconds)
    app.state.pipeline = pipeline

    # Read endpoints are async so they execute on the event-loop thread. Each
    # response is therefore a consistent snapshot of aggregator state with no
    # cross-thread race against the live feeder (which also runs on the loop).
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "flows_tracked": len(pipeline.aggregator.by_flow)}

    @app.get("/api/summary")
    async def summary():
        return pipeline.snapshot()

    @app.get("/api/jobs")
    async def jobs():
        rows = pipeline.aggregator.top_jobs()
        for row in rows:
            row["name"] = registry.name_of(row["job_id"]) or row["job_id"]
        return {"jobs": rows}

    @app.get("/api/jobs/{job_id}/flows")
    async def job_flows(job_id: str):
        return {
            "job_id": job_id,
            "name": registry.name_of(job_id) or job_id,
            "flows": pipeline.aggregator.flows_for_job(job_id),
        }

    @app.get("/api/jobs/{job_id}/timeseries")
    async def job_timeseries(job_id: str):
        return {"job_id": job_id, "series": pipeline.aggregator.series(job_id)}

    @app.post("/api/ingest")
    async def ingest(event: DropEvent):
        # async so pipeline.ingest (and WebSocket fan-out) runs on the loop.
        return pipeline.ingest(event).flat()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        pipeline.subscribers.add(q)
        try:
            await websocket.send_json({"type": "snapshot", "data": pipeline.snapshot()})
            while True:
                msg = await q.get()
                await websocket.send_json(msg)
        except WebSocketDisconnect:
            pass
        finally:
            pipeline.subscribers.discard(q)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
