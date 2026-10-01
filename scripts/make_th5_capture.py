#!/usr/bin/env python3
"""Generate a DUT-seeded MODSource capture from real TH5 (QFX5241) recon.

Provenance (captured 2026-07-31 from a QFX5241 lab DUT, TH5):
  SONiC 202511 (dev build)
  Platform x86_64-juniper_qfx5241-r0, HwSKU Juniper-QFX5241-64-OD
  Broadcom Tomahawk 5 / SAI 1.18

REAL from the DUT:
  * port names + up/down state (`show dropcounters counts`)
  * the chip's advertised PORT_INGRESS_DROPS reason set
    (`show dropcounters capabilities`)
  * observed RX_DROPS magnitudes

REPRESENTATIVE (pending MOD):
  * per-flow 5-tuple + RoCE QP. This box does NOT advertise
    MIRROR_ON_DROP_CAPABLE and orchagent/sflowmgrd carry zero MOD strings, so
    per-flow drop tuples are not exposed by the hardware today. They are
    synthesized within the scheduler-provided job subnets so the attribution
    pipeline can be exercised end-to-end on real DUT reasons/ports. This is the
    exact gap that live MOD (swss #3970 + a SAI that advertises the capability)
    would close.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- REAL DUT facts (from recon) ---------------------------------------------
UP_PORTS = ["Ethernet0", "Ethernet72"]           # observed admin/oper UP
# chip-advertised PORT_INGRESS_DROPS reasons (real, from the DUT):
REAL_REASONS = [
    "INGRESS_VLAN_FILTER", "EXCEEDS_L3_MTU", "ACL_ANY", "L3_EGRESS_LINK_DOWN",
    "IP_HEADER_ERROR", "TTL", "FDB_AND_BLACKHOLE_DISCARDS", "SMAC_EQUALS_DMAC",
]
# Scheduler-provided job topology (config/jobs.example.yaml) -> QP ranges:
JOB_SUBNETS = {"10.0.1": (1000, 1999), "10.0.2": (2000, 2999), "10.0.3": (3000, 3999)}
# incast-like weighting toward the first job, using REAL reasons/ports:
JOB_WEIGHTS = {"10.0.1": 6, "10.0.2": 2, "10.0.3": 2}


def generate(n: int = 60, seed: int = 20260731):
    rng = random.Random(seed)
    now = time.time()
    subnets = list(JOB_WEIGHTS)
    weights = [JOB_WEIGHTS[s] for s in subnets]
    for i in range(n):
        sub = rng.choices(subnets, weights=weights)[0]
        lo, hi = JOB_SUBNETS[sub]
        yield {
            "ts": round(now - (n - i) * 0.5, 3),   # ~0.5s spacing ending ~now
            "ingress_port": rng.choice(UP_PORTS),
            "src_ip": f"{sub}.{rng.randint(1, 254)}",
            "dst_ip": f"{sub}.{rng.randint(1, 254)}",
            "src_port": rng.randint(1024, 65535),
            "dst_port": 4791,
            "qp_num": rng.randint(lo, hi),
            "queue": rng.choice([0, 3]),
            "drop_reason": rng.choice(REAL_REASONS),
            "count": rng.randint(1, 4),
        }


def main():
    out = ROOT / "captures" / "th5-ug-seed.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# DUT-seeded MODSource capture -- provenance: scripts/make_th5_capture.py",
        "# ports/reasons are REAL from a QFX5241 DUT (TH5, SAI 1.18);",
        "# per-flow tuples are representative (MIRROR_ON_DROP_CAPABLE absent on this box).",
    ]
    lines = header + [json.dumps(rec) for rec in generate()]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote capture -> {out}")


if __name__ == "__main__":
    main()
