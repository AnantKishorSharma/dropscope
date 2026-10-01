# Per-Flow Drop Attribution for AI / RoCEv2 Fabrics (dropscope) — High Level Design

## Revision

| Rev | Date       | Author                              | Change               |
|-----|------------|-------------------------------------|----------------------|
| 0.1 | 2026-10-01 | Anant Kishor Sharma (HPE Juniper)   | Initial draft (SONiC Hackathon 2026) |

> Status: **design proposal / hackathon draft.** Not yet filed to `sonic-net/SONiC`.
> Intended upstream path is a `doc/` HLD PR after community review.

## Scope

This HLD describes a per-flow / per-job **drop attribution** layer for SONiC. It consumes
Mirror-on-Drop (MOD) dropped-packet notifications and maps each drop to the RoCEv2 flow
and AI training job it belongs to.

Out of scope: the MOD feature itself (SONiC #1786 / sonic-swss #3970); this design
*consumes* it and adds the attribution layer on top.

## Definitions / Abbreviations

MOD — Mirror-on-Drop · DPN — Dropped Packet Notification · QP — RDMA Queue Pair ·
IPFIX — IP Flow Information Export · HLD — High Level Design.

## Overview

AI training synchronizes across many GPUs over RoCEv2; a small number of silent drops on
one link can stall a collective and waste GPU-hours. SONiC exposes rich **aggregate** drop
telemetry (per-port / per-queue / per-reason counters, debug-counters; flow-counters are
per-route / per-trap) but nothing attributes an *individual* drop to the flow and training
job behind it. This design adds that per-flow / per-job attribution layer.

## Requirements

- Consume MOD/DPN drop exports (IPFIX) **without modifying the MOD datapath**.
- Attribute each drop to a 5-tuple flow and, where known, an AI job (via QP + subnet).
- Surface results via CLI and/or streaming telemetry; never over-claim — an explicit
  `unattributed` class is mandatory.
- Transport-agnostic: the same engine runs on synthetic test input and real MOD exports.

## Architecture

```
drop source (MOD/IPFIX | synthetic)
   -> correlation  (5-tuple + QP -> flow / job)
   -> aggregation  (rolling per-job/flow/queue/reason windows)
   -> export       (CLI / REST / gNMI-telemetry)
```

Components: `DropEvent` normalizer; `JobRegistry` (job -> host-subnets / QP-ranges);
`Correlator` (`DropEvent -> AttributedDrop`); `Aggregator`; pluggable export adapters.

## SONiC integration

- **Ingest:** subscribe to MOD IPFIX exports produced by the drop-monitor path
  (sfloworch / sonic-swss #3970), or read a local notification channel.
- **Run model:** an on-switch **feature container**, or an off-box **collector** container
  where the switch's MOD tunnel points.
- **Surface:** a `sonic-utilities` CLI (e.g. `show dropcounters flows`) and/or export over
  the existing **gNMI / telemetry** stack.
- **Config:** job topology from `CONFIG_DB` (or an external scheduler such as SLURM / K8s).

## Relationship to existing SONiC work

- **Builds on:** MOD HLD **SONiC #1786**, implementation **sonic-swss #3970** (merged to
  swss master 2026-09; delivers the dropped packet, no per-flow / per-job attribution).
- **Fills a gap:** SONiC's standard drop telemetry is aggregate (per-port / per-queue /
  per-reason counters, debug-counters; flow-counters are per-route / per-trap) — none tie
  a drop to its flow and training job.
- **Related (orthogonal):** *Forwarding Path Online Diagnostics* HLD **SONiC #2442** is an
  active probe-injection health check (its out-of-scope explicitly leaves drop counters
  alone); high-frequency telemetry / `countersyncd` IPFIX path (**sonic-swss #4732**).

## Data model

- `DropEvent{ts, ingress_port, egress_port, 5-tuple, qp_num, queue, drop_reason, count}`
- `AttributedDrop{DropEvent, job_id, flow_id}`
- `JobRegistry` entry `{id, name, host_subnets[], qp_range}`

## APIs, CLI & telemetry

- **REST + WebSocket API (implemented):** the attribution layer is API-first — a
  documented HTTP surface (OpenAPI at `/openapi.json`, Swagger `/docs`) that any app can
  consume: `GET /api/summary|jobs|jobs/{job}/flows|jobs/{job}/timeseries`, a live
  `WebSocket /ws`, and `POST /api/ingest` for any producer to push a `DropEvent`. The CLI
  and dashboard are just two clients.
- **CLI (implemented):** `dropscope show dropcounters flows|jobs|counts` (SONiC-style
  Click + tabulate); maps directly to `show dropcounters flows` in sonic-utilities.
- **Telemetry (proposed):** per-job / per-flow drop counters over gNMI; optional SONiC DB
  (Redis) table any SONiC app reads via swsssdk.

## Testing

- Unit tests for correlation / aggregation / sources (38 in the reference implementation).
- Replay of real DUT-seeded MOD captures; synthetic incast scenario for CI.

## Future work / open questions

- Standardize the MOD export schema consumed here.
- Remote-collector (network export) MOD in sonic-swss #3970, beyond the localhost / CPU model.
- `CONFIG_DB` schema for job topology; scale / performance targets.
