#!/usr/bin/env python3
"""Live bridge: real SONiC COUNTERS_DB drop counters -> dropscope.

Polls a SONiC DUT over an SSH ControlMaster socket, computes per-interval deltas
of REAL drop counters, and streams them into a running dropscope via
POST /api/ingest.

REAL from hardware (interface, drop-reason class, timestamp, delta magnitude):
  * per-port SAI_PORT_STAT_IF_IN/OUT_DISCARDS
  * switch  SAI_SWITCH_STAT_PACKET_INTEGRITY_DROP  (when the platform polls it)

REPRESENTATIVE (pending MOD): the per-flow 5-tuple/QP. Aggregate counters carry
no per-flow identity, so with --attribute a representative RoCEv2 flow within a
tracked job subnet is synthesized -- a clearly-labeled stand-in for what MOD
would provide. Without --attribute the real drops show as unattributed volume.

Setup:
    # 1) open an SSH master socket (you authenticate once):
    ssh -fN -M -S /tmp/ds-ug.sock -o ControlPersist=45m admin@<dut>
    # 2) run dropscope with no built-in source (HW-only):
    python -m dropscope.demo --source none
    # 3) run this bridge:
    python3 scripts/dut_counters_bridge.py --socket /tmp/ds-ug.sock --host <dut> \
        --ports Ethernet0,Ethernet72 --attribute
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import urllib.request

JOB_SUBNETS = {"10.0.1": (1000, 1999), "10.0.2": (2000, 2999), "10.0.3": (3000, 3999)}


def ssh_read(socket: str, user: str, host: str, snippet: str) -> str:
    cmd = ["ssh", "-S", socket, f"{user}@{host}", "bash -s"]
    proc = subprocess.run(cmd, input=snippet, capture_output=True, text=True, timeout=30)
    return proc.stdout


def build_snippet(ports) -> str:
    lines = [
        'SW=$(sonic-db-cli COUNTERS_DB HGET COUNTERS_DEBUG_NAME_SWITCH_STAT_MAP SWITCH_ID 2>/dev/null)',
        '[ -n "$SW" ] && echo "SWITCH PACKET_INTEGRITY '
        '$(sonic-db-cli COUNTERS_DB HGET COUNTERS:$SW SAI_SWITCH_STAT_PACKET_INTEGRITY_DROP 2>/dev/null)"',
    ]
    for p in ports:
        lines.append(
            f'oid=$(sonic-db-cli COUNTERS_DB HGET COUNTERS_PORT_NAME_MAP {p} 2>/dev/null); '
            f'echo "PORT {p} IN '
            f'$(sonic-db-cli COUNTERS_DB HGET COUNTERS:$oid SAI_PORT_STAT_IF_IN_DISCARDS 2>/dev/null) '
            f'OUT $(sonic-db-cli COUNTERS_DB HGET COUNTERS:$oid SAI_PORT_STAT_IF_OUT_DISCARDS 2>/dev/null)"'
        )
    return "\n".join(lines) + "\n"


def parse(out: str) -> dict:
    counters = {}
    for ln in out.splitlines():
        tok = ln.split()
        if len(tok) >= 3 and tok[0] == "SWITCH" and tok[2].isdigit():
            counters[("switch", tok[1])] = int(tok[2])
        elif len(tok) >= 6 and tok[0] == "PORT":
            port = tok[1]
            if tok[3].isdigit():
                counters[("port", port, "IN")] = int(tok[3])
            if tok[5].isdigit():
                counters[("port", port, "OUT")] = int(tok[5])
    return counters


def reason_for(key) -> str:
    return "PACKET_INTEGRITY" if key[0] == "switch" else "PORT_DISCARD"


def make_event(key, ts: float, rng: random.Random, attribute: bool) -> dict:
    port = key[1] if key[0] == "port" else "SwitchGlobal"
    ev = {"ts": ts, "ingress_port": port, "drop_reason": reason_for(key),
          "src_port": rng.randint(1024, 65535), "dst_port": 4791, "count": 1}
    if attribute:
        sub = rng.choices(list(JOB_SUBNETS), weights=[6, 2, 2])[0]
        lo, hi = JOB_SUBNETS[sub]
        ev.update(src_ip=f"{sub}.{rng.randint(1, 254)}",
                  dst_ip=f"{sub}.{rng.randint(1, 254)}", qp_num=rng.randint(lo, hi))
    else:
        ev.update(src_ip="0.0.0.0", dst_ip="0.0.0.0")
    return ev


def post(base_url: str, ev: dict) -> int:
    data = json.dumps(ev).encode()
    req = urllib.request.Request(base_url + "/api/ingest", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


def main() -> int:
    ap = argparse.ArgumentParser(description="live SONiC drop-counter bridge -> dropscope")
    ap.add_argument("--socket", required=True, help="ssh ControlMaster socket path")
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--dropscope", default="http://127.0.0.1:8000")
    ap.add_argument("--ports", default="Ethernet0,Ethernet72")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--attribute", action="store_true",
                    help="synthesize representative RoCEv2 flows (labeled) for attribution")
    ap.add_argument("--cap", type=int, default=50,
                    help="max events emitted per counter per interval")
    ap.add_argument("--backfill", action="store_true",
                    help="emit current accumulated counter values once at start "
                         "(not just future deltas)")
    args = ap.parse_args()

    ports = [p.strip() for p in args.ports.split(",") if p.strip()]
    snippet = build_snippet(ports)
    rng = random.Random(1337)

    print(f"[bridge] {args.host} -> {args.dropscope}  ports={ports} attribute={args.attribute}")
    print("[bridge] REAL: port/reason/ts/delta from HW; flows representative (pending MOD)"
          if args.attribute else
          "[bridge] REAL aggregate HW drops (unattributed; per-flow needs MOD)")

    try:
        prev = parse(ssh_read(args.socket, args.user, args.host, snippet))
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] initial read failed (is the socket up?): {exc}")
        return 1
    print("[bridge] baseline:", {str(k): v for k, v in prev.items()})

    if args.backfill:
        ts = time.time()
        n = 0
        for key, val in prev.items():
            for _ in range(min(val, args.cap)):
                try:
                    post(args.dropscope, make_event(key, ts, rng, args.attribute))
                    n += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[bridge] post failed: {exc}")
                    break
        print(f"[bridge] backfilled {n} real accumulated HW drops")

    while True:
        time.sleep(args.interval)
        try:
            cur = parse(ssh_read(args.socket, args.user, args.host, snippet))
        except Exception as exc:  # noqa: BLE001
            print(f"[bridge] read failed: {exc}")
            continue
        ts = time.time()
        emitted = 0
        for key, val in cur.items():
            delta = val - prev.get(key, val)
            if delta <= 0:
                continue
            for _ in range(min(delta, args.cap)):
                try:
                    post(args.dropscope, make_event(key, ts, rng, args.attribute))
                    emitted += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[bridge] post failed: {exc}")
                    break
        prev = cur
        if emitted:
            print(f"[bridge] +{emitted} real HW drop events streamed at "
                  f"{time.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    sys.exit(main())
