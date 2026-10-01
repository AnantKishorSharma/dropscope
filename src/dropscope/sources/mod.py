"""MOD (Mirror-on-Drop) source adapter -- the optional real-hardware input.

The community Mirror-on-Drop path (SONiC HLD #1786, swss #3970) emits
dropped-packet notifications. This adapter maps those into the same normalized
`DropEvent` schema the rest of the pipeline consumes. Because live MOD may not
be available (the swss PR is still open), this ships as a JSON Lines *replay*
adapter so a recorded capture can drive a real-data demo.
"""

from __future__ import annotations

import json
from typing import Iterable

from pydantic import ValidationError

from ..models import DropEvent, DropReason


# Map raw MOD/SAI drop-reason strings onto our enum. Unknown strings degrade
# gracefully to DropReason.UNKNOWN rather than raising.
_REASON_MAP = {
    "SAI_IN_DROP_REASON_ACL": DropReason.ACL_DENY,
    "SAI_OUT_DROP_REASON_EGRESS_BUFFER_FULL": DropReason.BUFFER_FULL,
    "SAI_OUT_DROP_REASON_WRED": DropReason.WRED,
    "SAI_IN_DROP_REASON_L3_NO_ROUTE": DropReason.L3_NO_ROUTE,
    "SAI_IN_DROP_REASON_MTU": DropReason.MTU_EXCEEDED,
    "BUFFER_FULL": DropReason.BUFFER_FULL,
    "WRED": DropReason.WRED,
    # SONiC debug-counter reason names as advertised by TH5/BCM SAI 1.18
    # (`show dropcounters capabilities` -> PORT_INGRESS_DROPS on QFX5241).
    "INGRESS_VLAN_FILTER": DropReason.INGRESS_VLAN,
    "EXCEEDS_L3_MTU": DropReason.MTU_EXCEEDED,
    "ACL_ANY": DropReason.ACL_DENY,
    "L3_EGRESS_LINK_DOWN": DropReason.L3_NO_ROUTE,
    # Real switch/port drop-stat names (live COUNTERS_DB on the DUT).
    "SAI_SWITCH_STAT_PACKET_INTEGRITY_DROP": DropReason.PACKET_INTEGRITY,
    "PACKET_INTEGRITY": DropReason.PACKET_INTEGRITY,
    "SAI_PORT_STAT_IF_IN_DISCARDS": DropReason.PORT_DISCARD,
    "SAI_PORT_STAT_IF_OUT_DISCARDS": DropReason.PORT_DISCARD,
}


def map_reason(raw) -> DropReason:
    if raw is None:
        return DropReason.UNKNOWN
    if isinstance(raw, DropReason):
        return raw
    return _REASON_MAP.get(str(raw), DropReason.UNKNOWN)


def normalize(record: dict) -> DropEvent:
    """Translate one MOD/notification record into a `DropEvent`."""
    return DropEvent(
        ts=float(record.get("ts") or record.get("timestamp") or 0.0),
        ingress_port=str(record.get("ingress_port") or record.get("port") or "?"),
        egress_port=record.get("egress_port"),
        src_ip=str(record.get("src_ip") or record.get("sip") or "0.0.0.0"),
        dst_ip=str(record.get("dst_ip") or record.get("dip") or "0.0.0.0"),
        l4_proto=int(record.get("l4_proto", 17)),
        src_port=int(record.get("src_port", 0)),
        dst_port=int(record.get("dst_port", 4791)),
        qp_num=(int(record["qp_num"]) if record.get("qp_num") is not None else None),
        queue=int(record.get("queue", 0)),
        drop_reason=map_reason(record.get("drop_reason")),
        count=int(record.get("count", 1)),
    )


class MODSource:
    """Replay MOD notifications from a JSON Lines file (one record per line)."""

    name = "mod"

    def __init__(self, path: str):
        self.path = path

    def events(self) -> Iterable[DropEvent]:
        with open(self.path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    event = normalize(record)
                except (json.JSONDecodeError, ValidationError, ValueError,
                        TypeError, KeyError):
                    continue  # skip malformed records rather than abort the feed
                yield event
