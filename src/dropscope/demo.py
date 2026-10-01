"""Live demo driver.

Loads the example job topology + scenario, builds the FastAPI app, and replays
the synthetic drop stream in real time (rebasing timestamps to now) while a
ticker pushes rolling summaries to the dashboard over WebSocket.

    python -m dropscope.demo            # http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from pathlib import Path

import uvicorn
import yaml

from .api import create_app
from .registry import JobRegistry
from .sources.mod import MODSource
from .sources.mod_live import MODLiveSource
from .sources.synthetic import SyntheticSource

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_defaults():
    registry = JobRegistry.from_yaml(str(CONFIG_DIR / "jobs.example.yaml"))
    with open(CONFIG_DIR / "scenario.example.yaml") as fh:
        scenario = yaml.safe_load(fh)
    return registry, scenario


async def _feed(pipeline, events, speed: float, loop_forever: bool) -> None:
    while True:
        prev = None
        for ev in events:
            if prev is not None:
                delay = (ev.ts - prev) / speed
                if delay > 0:
                    await asyncio.sleep(min(delay, 1.0))
            prev = ev.ts
            pipeline.ingest(ev.model_copy(update={"ts": time.time()}))
        if not loop_forever:
            break
        await asyncio.sleep(1.0)


async def _tick(pipeline) -> None:
    while True:
        await asyncio.sleep(1.0)
        pipeline._broadcast({"type": "summary", "data": pipeline.snapshot()})


def build_live_app(speed: float = 4.0, loop_forever: bool = True,
                   source: str = "synthetic", capture: str = None,
                   bind_host: str = "0.0.0.0", bind_port: int = 31337,
                   ingress: str = "?", egress: str = None,
                   reason: str = "SAI_IN_DROP_REASON_ACL"):
    registry, scenario = load_defaults()
    live = None
    events = []
    if source == "mod":
        if not capture:
            raise SystemExit("--source mod requires --capture <jsonl file>")
        events = list(MODSource(capture).events())
        if not events:
            raise SystemExit(f"no valid drop events parsed from {capture}")
    elif source == "mod-live":
        live = MODLiveSource(bind_host, bind_port, ingress, egress, reason)
    elif source == "none":
        events = []   # external source (e.g. the live DUT bridge) feeds /api/ingest
    else:
        events = SyntheticSource(registry, scenario).generate(start_epoch=0.0)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        pipeline = app.state.pipeline
        tasks = [asyncio.create_task(_tick(pipeline))]
        if events:
            tasks.append(asyncio.create_task(_feed(pipeline, events, speed, loop_forever)))
        if live is not None:
            tasks.append(asyncio.create_task(live.run(pipeline.ingest)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return create_app(registry, lifespan=lifespan)


def main():
    parser = argparse.ArgumentParser(description="dropscope live demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--speed", type=float, default=4.0,
                        help="scenario/capture replay speed multiplier")
    parser.add_argument("--source", choices=["synthetic", "mod", "mod-live", "none"],
                        default="synthetic", help="drop-event source")
    parser.add_argument("--capture", default=None,
                        help="JSONL capture path (required for --source mod)")
    parser.add_argument("--bind-host", default="0.0.0.0",
                        help="UDP bind host for --source mod-live")
    parser.add_argument("--bind-port", type=int, default=31337,
                        help="UDP bind port for --source mod-live (MOD export port)")
    parser.add_argument("--ingress", default="?",
                        help="ingress port label for live MOD drops")
    parser.add_argument("--egress", default=None,
                        help="egress (mirror) port label for live MOD drops")
    parser.add_argument("--reason", default="SAI_IN_DROP_REASON_ACL",
                        help="drop reason label for live MOD drops")
    args = parser.parse_args()

    app = build_live_app(speed=args.speed, source=args.source, capture=args.capture,
                         bind_host=args.bind_host, bind_port=args.bind_port,
                         ingress=args.ingress, egress=args.egress, reason=args.reason)
    print(f"dropscope demo -> http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
