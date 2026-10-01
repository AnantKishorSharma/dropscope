"""Rolling aggregation of attributed drops for the API and dashboard.

Maintains running totals (per job / flow / queue / reason) plus a time-bucketed
series over a sliding window so the dashboard can render a live chart.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from .models import AttributedDrop

UNATTRIBUTED = "unattributed"


class Aggregator:
    def __init__(self, window_seconds: int = 120, bucket_seconds: int = 1):
        self.window_seconds = window_seconds
        self.bucket_seconds = max(1, bucket_seconds)

        self.total_drops = 0
        self.by_job: Dict[str, int] = defaultdict(int)
        self.by_flow: Dict[str, int] = defaultdict(int)
        self.by_queue: Dict[str, int] = defaultdict(int)
        self.by_reason: Dict[str, int] = defaultdict(int)

        # flow_id -> descriptive metadata (last seen)
        self.flow_meta: Dict[str, dict] = {}
        # flow_id -> owning job (or UNATTRIBUTED)
        self._flow_job: Dict[str, str] = {}

        # time buckets: bucket_ts -> count (total and per-job)
        self._buckets: Dict[int, int] = defaultdict(int)
        self._job_buckets: Dict[str, Dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.latest_ts: float = 0.0

    def _bucket_of(self, ts: float) -> int:
        return int(ts // self.bucket_seconds) * self.bucket_seconds

    def ingest(self, ad: AttributedDrop) -> None:
        c = ad.event.count
        job = ad.job_id or UNATTRIBUTED

        self.total_drops += c
        self.by_job[job] += c
        self.by_flow[ad.flow_id] += c
        self.by_queue[str(ad.event.queue)] += c
        self.by_reason[ad.event.drop_reason.value] += c

        self.flow_meta[ad.flow_id] = {
            "flow_key": ad.flow_key,
            "job_id": ad.job_id,
            "role": ad.endpoint_role.value,
            "queue": ad.event.queue,
            "drop_reason": ad.event.drop_reason.value,
        }
        self._flow_job[ad.flow_id] = job

        b = self._bucket_of(ad.event.ts)
        self._buckets[b] += c
        self._job_buckets[job][b] += c
        self.latest_ts = max(self.latest_ts, ad.event.ts)
        self._evict()

    def _evict(self) -> None:
        cutoff = self.latest_ts - self.window_seconds
        for b in [b for b in self._buckets if b < cutoff]:
            del self._buckets[b]
        for job, buckets in self._job_buckets.items():
            for b in [b for b in buckets if b < cutoff]:
                del buckets[b]

    # ---- read APIs -------------------------------------------------------

    def top_jobs(self, limit: int = 10) -> List[dict]:
        items = sorted(self.by_job.items(), key=lambda kv: kv[1], reverse=True)
        return [{"job_id": j, "drops": n} for j, n in items[:limit]]

    def series(self, job: Optional[str] = None) -> List[dict]:
        """Contiguous per-second series over the window (gaps filled with 0)."""
        if self.latest_ts == 0.0:
            return []
        buckets = (self._job_buckets.get(job, {}) if job else self._buckets)
        end = self._bucket_of(self.latest_ts)
        start = end - self.window_seconds
        out = []
        t = start
        while t <= end:
            out.append({"ts": t, "drops": buckets.get(t, 0)})
            t += self.bucket_seconds
        return out

    def flows_for_job(self, job: str, limit: int = 20) -> List[dict]:
        rows = []
        for flow_id, owner in self._flow_job.items():
            if owner != job:
                continue
            meta = self.flow_meta.get(flow_id, {})
            rows.append(
                {
                    "flow_id": flow_id,
                    "flow_key": meta.get("flow_key"),
                    "role": meta.get("role"),
                    "queue": meta.get("queue"),
                    "drop_reason": meta.get("drop_reason"),
                    "drops": self.by_flow.get(flow_id, 0),
                }
            )
        rows.sort(key=lambda r: r["drops"], reverse=True)
        return rows[:limit]

    def summary(self) -> dict:
        return {
            "total_drops": self.total_drops,
            "top_jobs": self.top_jobs(),
            "by_reason": dict(self.by_reason),
            "by_queue": dict(self.by_queue),
            "series": self.series(),
            "latest_ts": self.latest_ts,
            "flows_tracked": len(self.by_flow),
        }
