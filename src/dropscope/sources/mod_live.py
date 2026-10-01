"""Live MOD source: receive real Mirror-on-Drop IPFIX exports over UDP.

Runs dropscope *on the collector* (or anywhere the switch's MOD tunnel is
pointed) and turns each export datagram into a `DropEvent` in real time -- the
same normalized event the synthetic and replay sources produce, so the
correlation/aggregation/dashboard layers are unchanged.

The datagram handler is deliberately split from the socket so it is unit-testable
without a running event loop: `MODDatagramProtocol.datagram_received` can be
called directly with raw bytes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from ..models import DropEvent
from ..modparse import parse_embedded
from .mod import map_reason

# Broadcom MOD IPFIX export UDP port (0x7a69).
MOD_EXPORT_PORT = 31337


class MODDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_event: Callable[[DropEvent], None],
                 ingress_port: str, egress_port: Optional[str], reason: str):
        self.on_event = on_event
        self.ingress_port = ingress_port
        self.egress_port = egress_port
        self.reason = reason

    def to_event(self, data: bytes) -> Optional[DropEvent]:
        flow = parse_embedded(data)
        if flow is None:
            return None
        return DropEvent(
            ts=time.time(),
            ingress_port=self.ingress_port,
            egress_port=self.egress_port,
            src_ip=flow["src_ip"],
            dst_ip=flow["dst_ip"],
            l4_proto=flow["l4_proto"],
            src_port=flow["src_port"],
            dst_port=flow["dst_port"],
            qp_num=flow["qp_num"],
            drop_reason=map_reason(self.reason),
        )

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            ev = self.to_event(data)
        except (ValueError, IndexError, TypeError):
            return  # skip a malformed datagram rather than kill the listener
        if ev is not None:
            self.on_event(ev)


class MODLiveSource:
    """Async UDP listener that pushes live MOD drops into a callback."""

    name = "mod-live"

    def __init__(self, host: str = "0.0.0.0", port: int = MOD_EXPORT_PORT,
                 ingress_port: str = "?", egress_port: Optional[str] = None,
                 reason: str = "SAI_IN_DROP_REASON_ACL"):
        self.host = host
        self.port = port
        self.ingress_port = ingress_port
        self.egress_port = egress_port
        self.reason = reason
        self._transport = None

    async def run(self, on_event: Callable[[DropEvent], None]) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: MODDatagramProtocol(on_event, self.ingress_port,
                                        self.egress_port, self.reason),
            local_addr=(self.host, self.port),
        )
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            if self._transport is not None:
                self._transport.close()
