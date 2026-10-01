"""Training-job topology: map host IPs / RoCE QP ranges to a job.

In a real deployment this mapping comes from the job scheduler (SLURM, K8s,
etc.). Here it is loaded from a static YAML file for a self-contained demo.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import yaml


@dataclass
class Job:
    job_id: str
    name: str
    hosts: List[str]  # IPs or CIDRs owned by the job
    qp_range: Optional[Tuple[int, int]] = None
    _nets: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._nets = [ipaddress.ip_network(h, strict=False) for h in self.hosts]

    def contains_ip(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self._nets)

    def contains_qp(self, qp: Optional[int]) -> bool:
        # No QP constraint, or event has no QP -> do not exclude on QP.
        if self.qp_range is None or qp is None:
            return True
        lo, hi = self.qp_range
        return lo <= qp <= hi

    @property
    def networks(self):
        return self._nets


class JobRegistry:
    def __init__(self, jobs: List[Job]):
        self.jobs = jobs
        self._by_id = {j.job_id: j for j in jobs}

    @classmethod
    def from_dict(cls, data: dict) -> "JobRegistry":
        jobs: List[Job] = []
        for j in (data or {}).get("jobs", []):
            qp = j.get("qp_range")
            qp_range = (int(qp[0]), int(qp[1])) if qp else None
            jobs.append(
                Job(
                    job_id=j["id"],
                    name=j.get("name", j["id"]),
                    hosts=list(j.get("hosts", [])),
                    qp_range=qp_range,
                )
            )
        return cls(jobs)

    @classmethod
    def from_yaml(cls, path: str) -> "JobRegistry":
        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh))

    def name_of(self, job_id: Optional[str]) -> Optional[str]:
        job = self._by_id.get(job_id) if job_id else None
        return job.name if job else None

    def names(self) -> dict:
        return {j.job_id: j.name for j in self.jobs}

    def get(self, job_id: Optional[str]) -> Optional[Job]:
        return self._by_id.get(job_id) if job_id else None

    def match(self, ip: str, qp: Optional[int] = None) -> Optional[Job]:
        """Return the first job that owns `ip` (and QP, if constrained)."""
        for job in self.jobs:
            if job.contains_ip(ip) and job.contains_qp(qp):
                return job
        return None
