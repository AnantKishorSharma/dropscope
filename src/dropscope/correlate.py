"""Correlation engine: turn a raw `DropEvent` into an `AttributedDrop`.

This is the novel contribution of the project: mapping each real dropped packet
to the specific RoCEv2 flow and training job it affected. Kept small and pure so
it is trivially unit-testable and cleanly extractable into swss/gnmi later.
"""

from __future__ import annotations

from .models import AttributedDrop, DropEvent, EndpointRole
from .registry import JobRegistry


class Correlator:
    def __init__(self, registry: JobRegistry):
        self.registry = registry

    def attribute(self, event: DropEvent) -> AttributedDrop:
        job_id = None
        role = EndpointRole.UNKNOWN

        # A drop is attributed to a job if either endpoint belongs to it.
        # Prefer the source (the sender whose transmission was dropped),
        # then fall back to the destination (receiver).
        src_job = self.registry.match(event.src_ip, event.qp_num)
        dst_job = self.registry.match(event.dst_ip, event.qp_num)

        if src_job is not None:
            job_id = src_job.job_id
            role = EndpointRole.SENDER
        elif dst_job is not None:
            job_id = dst_job.job_id
            role = EndpointRole.RECEIVER

        return AttributedDrop(
            event=event,
            flow_id=event.flow_id(),
            flow_key=event.flow_key(),
            job_id=job_id,
            endpoint_role=role,
        )
