"""Normalized data model for dropped-packet events and their attribution.

The `DropEvent` schema is intentionally aligned with the fields a SONiC
Mirror-on-Drop (MOD) notification carries, so the real `MODSource` adapter is a
thin mapping rather than a rewrite.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field

# RoCEv2 runs over UDP with this destination port; the BTH (Base Transport
# Header) carries the destination Queue Pair (QP) used to identify a flow.
ROCEV2_UDP_PORT = 4791


class DropReason(str, Enum):
    BUFFER_FULL = "BUFFER_FULL"
    WRED = "WRED"
    ACL_DENY = "ACL_DENY"
    MTU_EXCEEDED = "MTU_EXCEEDED"
    INGRESS_VLAN = "INGRESS_VLAN"
    L3_NO_ROUTE = "L3_NO_ROUTE"
    PACKET_INTEGRITY = "PACKET_INTEGRITY"   # SAI_SWITCH_STAT_PACKET_INTEGRITY_DROP
    PORT_DISCARD = "PORT_DISCARD"           # SAI_PORT_STAT_IF_IN/OUT_DISCARDS
    UNKNOWN = "UNKNOWN"


class EndpointRole(str, Enum):
    SENDER = "sender"
    RECEIVER = "receiver"
    UNKNOWN = "unknown"


class DropEvent(BaseModel):
    """A single dropped-packet notification, normalized across producers."""

    ts: float = Field(..., description="Unix timestamp of the drop")
    ingress_port: str
    egress_port: Optional[str] = None
    src_ip: str
    dst_ip: str
    l4_proto: int = Field(default=17, ge=0, le=255)  # UDP by default (RoCEv2)
    src_port: int = Field(default=0, ge=0, le=65535)
    dst_port: int = Field(default=ROCEV2_UDP_PORT, ge=0, le=65535)
    qp_num: Optional[int] = Field(default=None, ge=0, le=0xFFFFFF)  # 24-bit QP
    queue: int = Field(default=0, ge=0, le=255)
    drop_reason: DropReason = DropReason.UNKNOWN
    count: int = Field(default=1, ge=1)

    def flow_key(self) -> str:
        """Human-readable stable key for the 5-tuple (+ QP for RoCEv2)."""
        key = (
            f"{self.src_ip}:{self.src_port}->{self.dst_ip}:{self.dst_port}"
            f"/{self.l4_proto}"
        )
        if self.qp_num is not None:
            key += f"#qp{self.qp_num}"
        return key

    def flow_id(self) -> str:
        """Short stable identifier derived from the flow key.

        blake2b (not SHA-1) is used purely as a fast, stable display hash; it
        carries no security meaning but avoids SHA-1 optics in public review.
        """
        return hashlib.blake2b(self.flow_key().encode(), digest_size=6).hexdigest()


class AttributedDrop(BaseModel):
    """A `DropEvent` enriched with flow and training-job attribution."""

    event: DropEvent
    flow_id: str
    flow_key: str
    job_id: Optional[str] = None
    endpoint_role: EndpointRole = EndpointRole.UNKNOWN

    def flat(self) -> Dict[str, object]:
        """Flatten to a plain dict for JSON transport / dashboard."""
        e = self.event
        return {
            "ts": e.ts,
            "ingress_port": e.ingress_port,
            "egress_port": e.egress_port,
            "src_ip": e.src_ip,
            "dst_ip": e.dst_ip,
            "src_port": e.src_port,
            "dst_port": e.dst_port,
            "qp_num": e.qp_num,
            "queue": e.queue,
            "drop_reason": e.drop_reason.value,
            "count": e.count,
            "flow_id": self.flow_id,
            "flow_key": self.flow_key,
            "job_id": self.job_id,
            "endpoint_role": self.endpoint_role.value,
        }
