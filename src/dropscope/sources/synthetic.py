"""Synthetic drop-event source.

Deterministically generates a realistic stream of dropped-packet events from a
scenario description (phases with per-job weights, drop reasons, rates). This is
the primary, always-works demo path -- no hardware or external services required.
"""

from __future__ import annotations

import ipaddress
import random
from typing import Dict, List, Optional

from ..models import DropEvent, DropReason
from ..registry import JobRegistry
from .base import DropEventSource


class SyntheticSource(DropEventSource):
    name = "synthetic"

    def __init__(self, registry: JobRegistry, scenario: dict):
        self.registry = registry
        self.scenario = scenario or {}
        self.rng = random.Random(self.scenario.get("seed", 0))
        pool = self.scenario.get("unattributed_pool", "10.9.9.0/24")
        self._unattributed_net = ipaddress.ip_network(pool, strict=False)

    # ---- helpers ---------------------------------------------------------

    def _host_in(self, net) -> str:
        base = int(net.network_address)
        span = max(1, net.num_addresses - 2)
        offset = self.rng.randint(1, min(254, span))
        return str(ipaddress.ip_address(base + offset))

    def _endpoints(self, job_id: str):
        """Return (src_ip, dst_ip, qp) for a flow belonging to `job_id`."""
        if job_id == "unattributed":
            src = self._host_in(self._unattributed_net)
            dst = self._host_in(self._unattributed_net)
            return src, dst, self.rng.randint(1, 65535)

        job = self.registry.get(job_id)
        if job is None or not job.networks:
            src = self._host_in(self._unattributed_net)
            return src, self._host_in(self._unattributed_net), None

        net = job.networks[0]
        src = self._host_in(net)
        dst = self._host_in(net)
        qp = None
        if job.qp_range:
            lo, hi = job.qp_range
            qp = self.rng.randint(lo, hi)
        return src, dst, qp

    def _weighted(self, weights: Dict[str, float]) -> str:
        keys = list(weights.keys())
        vals = [max(0.0, float(weights[k])) for k in keys]
        return self.rng.choices(keys, weights=vals, k=1)[0]

    def _phase_at(self, t: int) -> Optional[dict]:
        for ph in self.scenario.get("phases", []):
            start = ph.get("start", 0)
            if start <= t < start + ph.get("duration", 0):
                return ph
        return None

    # ---- generation ------------------------------------------------------

    def generate(self, start_epoch: float = 0.0) -> List[DropEvent]:
        """Produce the full deterministic event list for the scenario."""
        duration = int(self.scenario.get("duration_seconds", 60))
        base_rate = int(self.scenario.get("base_rate_pps", 5))
        ports = self.scenario.get("fabric_ports", ["Ethernet0"])
        events: List[DropEvent] = []

        for t in range(duration):
            phase = self._phase_at(t)
            if phase is None:
                continue
            rate = int(phase.get("rate_pps", base_rate))
            weights = phase.get("weights", {"unattributed": 1})
            reasons = phase.get("reasons", {"UNKNOWN": 1})
            queue = int(phase.get("queue", 0))

            for i in range(rate):
                job_id = self._weighted(weights)
                src, dst, qp = self._endpoints(job_id)
                reason = DropReason(self._weighted(reasons))
                ingress = self.rng.choice(ports)
                egress = self.rng.choice(ports)
                ts = start_epoch + t + (i / max(1, rate))
                events.append(
                    DropEvent(
                        ts=ts,
                        ingress_port=ingress,
                        egress_port=egress,
                        src_ip=src,
                        dst_ip=dst,
                        src_port=self.rng.randint(1024, 65535),
                        qp_num=qp,
                        queue=queue,
                        drop_reason=reason,
                        count=1,
                    )
                )
        return events

    def events(self):
        return self.generate()
