# dropscope

Real-time **drop attribution for AI / RoCEv2 fabrics** in SONiC.

Silent packet drops stall AI training jobs, yet SONiC's drop telemetry is *aggregate*
(per-port / per-queue / per-reason) — it doesn't tie a drop to the RoCEv2 flow and the
training job behind it. `dropscope` is a transport-agnostic collector that consumes
dropped-packet notifications, **correlates each drop to a specific RoCEv2 flow and
training job**, and exposes the result through a live dashboard and a queryable API.

The attribution engine is decoupled from any single producer:

- **Synthetic source** (primary, always works) — replays a scripted incast
  scenario so the end-to-end demo is fully self-contained and reproducible.
- **MOD source** (pluggable, optional) — adapts real Mirror-on-Drop / dropped
  packet notifications into the same normalized schema for a real-hardware run.

> This is a vendor-neutral, upstream-oriented project. SONiC's drop telemetry is
> *aggregate* (per-port / per-queue / per-reason counters, debug-counters); even the
> finer-grained options (ACL-rule counters, sFlow) don't tie a drop to its RoCEv2 flow
> and the training job behind it. `dropscope` adds that attribution layer on top of
> SONiC Mirror-on-Drop (HLD #1786 / swss #3970).

## Quick start

```bash
make install     # create venv + install
make test        # run the unit tests
make demo        # live demo at http://127.0.0.1:8000
```

## CLI — SONiC-style `show dropcounters`

A reference CLI mirrors the sonic-utilities `show` UX (Click + tabulate), reading the
live demo API (run `make demo` first):

```bash
dropscope show dropcounters flows    # per-flow attribution: flow + QP -> job + reason
dropscope show dropcounters jobs     # per-job drop totals
dropscope show dropcounters counts   # per-reason totals (parallels `show dropcounters counts`)
```

In sonic-utilities this registers as `show dropcounters flows` — the per-flow extension
to the existing `show dropcounters` family.

## API — reusable by any app

dropscope is **API-first**: the CLI and dashboard are just two clients, so any app can
consume the same HTTP surface. It's self-documented via **OpenAPI** (`/openapi.json`),
with Swagger UI at `/docs` and ReDoc at `/redoc`.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/summary` | totals + top jobs |
| `GET /api/jobs` | per-job drop counts |
| `GET /api/jobs/{job}/flows` | per-flow attribution for a job |
| `GET /api/jobs/{job}/timeseries` | per-job time series |
| `POST /api/ingest` | push a `DropEvent` from **any** producer; returns the attributed drop |
| `GET /ws` (WebSocket) | live snapshot + per-drop stream |
| `GET /api/health` | liveness |

```bash
curl -s localhost:8000/api/jobs | jq         # read attribution from any language
curl -s localhost:8000/openapi.json          # machine-readable contract -> generate a client
```

## Real-hardware input (MOD capture replay)

`MODSource` ingests dropped-packet notifications as JSON Lines, so a capture
from real hardware drives the very same pipeline:

```bash
python -m dropscope.demo --source mod --capture captures/th5-ug-seed.jsonl
```

`captures/th5-ug-seed.jsonl` is DUT-seeded from a Broadcom TH5 (Juniper QFX5241,
SONiC 202511): **real** ports + the chip's **real** advertised drop-reason set,
with representative per-flow tuples. See `captures/th5-ug-recon.txt` for the
on-box evidence that this platform does not advertise `MIRROR_ON_DROP_CAPABLE`
— full live MOD needs a build that includes swss #3970 (merged to swss master 2026-09)
plus a SAI that advertises MOD.

### Live MOD (real IPFIX exports over UDP)

Run dropscope **on the collector** (or wherever the switch's MOD tunnel points)
to ingest real Mirror-on-Drop IPFIX exports in real time — no capture file:

```bash
python -m dropscope.demo --source mod-live --bind-port 31337 \
    --ingress Ethernet72 --egress Ethernet0
```

Each export datagram is parsed (`dropscope.modparse`) to recover the embedded
dropped 5-tuple + RoCEv2 BTH QP and fed straight into the same pipeline. A raw
`th5-ug-roce-e2e.jsonl` produced from a live run (`scripts/pcap_to_mod_jsonl.py`)
replays the identical data with `--source mod`.


## Architecture

```
drop source (synthetic | MOD)  ->  correlation engine  ->  aggregator  ->  API + WebSocket  ->  dashboard
   pluggable DropEvent stream       5-tuple+QP -> flow/job   rolling windows    REST + /ws        live view
```

## Layout

```
src/dropscope/
  models.py       DropEvent, AttributedDrop, enums
  registry.py     JobRegistry: job -> hosts/QP topology
  correlate.py    Correlator: DropEvent -> AttributedDrop   (core IP)
  aggregate.py    Aggregator: rolling per-job/flow/queue/reason stats
  sources/        base.py, synthetic.py, mod.py
  api.py          FastAPI REST + WebSocket + static dashboard
  demo.py         live scenario driver
config/           jobs.example.yaml, scenario.example.yaml
web/              index.html, app.js  (Chart.js dashboard)
tests/            pytest suite
```

## SONiC integration & upstream path

dropscope is a SONiC ecosystem component: it **consumes** SONiC's Mirror-on-Drop (MOD)
dropped-packet notifications and adds the per-flow / per-job attribution that SONiC's
aggregate drop telemetry doesn't provide.

- **Consumes:** Mirror-on-Drop / Dropped-Packet-Notification — HLD SONiC #1786, impl
  sonic-swss #3970. `MODSource` ingests the IPFIX drop exports the switch emits; MOD
  delivers the dropped packet, dropscope attributes it to a flow and job.
- **Fills a real gap:** SONiC's standard drop telemetry is aggregate (per-port / per-queue
  / per-reason counters, debug-counters); even ACL-rule counters or sFlow don't map a drop
  to its RoCEv2 flow **and** the training job behind it.
- **Where it lands in SONiC:** the correlation layer runs as an on-switch (or collector)
  feature container, surfacing attribution through a `sonic-utilities` CLI
  (**implemented here** as `dropscope show dropcounters flows`; maps to `show dropcounters
  flows`) and/or the standard gNMI / telemetry export path.
- **Upstream path:** (1) an HLD design doc ([docs/hld-drop-attribution.md](docs/hld-drop-attribution.md))
  proposing per-flow drop attribution as a SONiC feature; (2) a `sonic-utilities` CLI;
  (3) a follow-up to sonic-swss #3970 adding remote-collector (network export) MOD,
  beyond the localhost / CPU model.

## SONiC Hackathon 2026 submission

- **Project title:** dropscope — per-flow drop attribution for AI / RoCEv2 fabrics
  with SONiC Mirror-on-Drop
- **Team:** solo — Anant Kishor Sharma
- **Company:** HPE Juniper
- **Status:** Completed
- **Category:** Network for AI

**What's new for SONiC.** SONiC surfaces rich *aggregate* drop telemetry (per-port /
per-queue / per-reason counters, debug-counters; flow-counters are per-route / per-trap)
but nothing maps an individual drop to the RoCEv2 flow and AI training job it belongs to.
dropscope adds that missing per-flow / per-job attribution layer on top of SONiC
Mirror-on-Drop (HLD #1786 / swss #3970).

**Provenance (per hackathon rules — please confirm the exact split).**

- *Community / pre-existing (not our work):* the Mirror-on-Drop / Dropped-Packet-
  Notification feature itself — HLD SONiC #1786 and the swss #3970 impl (merged to
  swss master 2026-09).
- *Built as this project:* the entire `dropscope` codebase — the correlation engine
  (`correlate.py`), job/QP registry, rolling aggregator, pluggable drop sources
  (synthetic incast + live MOD/IPFIX), the FastAPI + WebSocket dashboard, the
  `pcap → MOD JSONL` converter, and the test suite; plus the end-to-end hardware
  bring-up that produced the real capture replays under `captures/`.

**Links.**

- Demo: `make demo` → http://127.0.0.1:8000 (synthetic source, no hardware needed)
- Community references: SONiC #1786 (MOD HLD), sonic-swss #3970 (MOD impl)

> Vendor-neutral submission: this repository contains only the open, vendor-neutral
> attribution tool and platform-agnostic replay data. Platform SAI enablement details
> are intentionally out of scope here.

## License

Apache-2.0 — see [LICENSE](LICENSE). © 2026 the dropscope authors.
