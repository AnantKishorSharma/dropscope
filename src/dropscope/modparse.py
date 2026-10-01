"""Parse a Broadcom Mirror-on-Drop (MOD) IPFIX export into flow fields.

A MOD export encapsulates the *original dropped packet* inside an IPFIX record.
Both the recorded-capture converter and the live UDP listener need to pull the
embedded 5-tuple (and RoCEv2 QP) back out, so the logic lives here once.

The embedded L2 frame follows a fixed IPFIX data-record marker; we locate it by
the marker, read its 2-byte length, then parse the inner Ethernet/IPv4/L4
headers. Works whether `buf` is a full captured frame or just the export UDP
payload, because we search for the marker rather than assume an offset.
"""

from __future__ import annotations

from typing import Optional, TypedDict

# IPFIX data-record marker that immediately precedes the 2-byte embedded-frame
# length + the embedded original dropped L2 frame.
MOD_RECORD_MARKER = b"\x10\x00\x12\x34\x00\xff"

ROCEV2_UDP_PORT = 4791


class EmbeddedFlow(TypedDict):
    src_ip: str
    dst_ip: str
    l4_proto: int
    src_port: int
    dst_port: int
    qp_num: Optional[int]


def parse_embedded(buf: bytes) -> Optional[EmbeddedFlow]:
    """Return the embedded dropped flow, or None if `buf` has no IPv4 embed."""
    idx = buf.find(MOD_RECORD_MARKER)
    if idx < 0:
        return None
    flen = int.from_bytes(buf[idx + 6:idx + 8], "big")
    frame = buf[idx + 8:idx + 8 + flen]
    if len(frame) < 14 + 20:
        return None
    if int.from_bytes(frame[12:14], "big") != 0x0800:   # IPv4 embeds only
        return None
    ip = frame[14:]
    ihl = (ip[0] & 0x0F) * 4
    if len(ip) < ihl:
        return None
    proto = ip[9]
    src_ip = ".".join(str(b) for b in ip[12:16])
    dst_ip = ".".join(str(b) for b in ip[16:20])
    sport = dport = 0
    qp: Optional[int] = None
    if proto in (6, 17) and len(ip) >= ihl + 4:          # TCP / UDP
        sport = int.from_bytes(ip[ihl:ihl + 2], "big")
        dport = int.from_bytes(ip[ihl + 2:ihl + 4], "big")
        if proto == 17 and dport == ROCEV2_UDP_PORT:     # RoCEv2 -> BTH QP
            bth = ip[ihl + 8:]
            if len(bth) >= 8:
                qp = (bth[5] << 16) | (bth[6] << 8) | bth[7]
    return EmbeddedFlow(src_ip=src_ip, dst_ip=dst_ip, l4_proto=proto,
                        src_port=sport, dst_port=dport, qp_num=qp)
