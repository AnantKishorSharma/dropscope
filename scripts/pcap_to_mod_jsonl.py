#!/usr/bin/env python3
"""Convert a REAL Broadcom Mirror-on-Drop capture (pcap) into dropscope MODSource
JSON Lines.

Unlike ``make_th5_capture.py`` (which seeds representative tuples), this reads an
*actual* MOD/IPFIX export capture taken on the collector's Ethernet0 during the
TH5 end-to-end run and extracts the genuine dropped-flow 5-tuple that the chip
embedded inside each export packet.

MOD export packet layout (verified on TH5 / QFX5241, SAI 1.18):
    [outer Eth][outer IPv4 10.123.0.1->10.123.0.2][UDP 31337->31337]
    [IPFIX v10 hdr][set id 0x1234 ...][marker 10 00 12 34 00 ff][len:2][EMBEDDED L2 FRAME]

The embedded L2 frame is the *original dropped packet* (inner Eth + IPv4 + L4).
We locate it by the fixed 6-byte record marker, read its 2-byte length, then parse
the inner Ethernet/IPv4/L4 headers. Non-IPv4 embeds (e.g. a dropped ARP) are skipped.

Usage:
    python scripts/pcap_to_mod_jsonl.py path/to/mod_capture.pcap \
        --ingress Ethernet72 --egress Ethernet0 --reason SAI_IN_DROP_REASON_ACL \
        > captures/th5-ug-live-e2e.jsonl
"""

from __future__ import annotations

import argparse
import json
import struct
import sys

# IPFIX data-record marker that immediately precedes the 2-byte embedded-frame
# length + the embedded original dropped L2 frame.
_MOD_RECORD_MARKER = b"\x10\x00\x12\x34\x00\xff"


# Link-layer header length by pcap DLT/linktype.
_L2_LEN = {1: 14, 113: 16, 101: 0, 12: 0, 0: 4}   # EN10MB, LINUX_SLL, RAW, RAW, NULL

_MOD_UDP_PORT = 31337     # Broadcom MOD IPFIX export UDP port (0x7a69)
_ROCE_UDP_PORT = 4791     # RoCEv2 (InfiniBand-over-UDP) destination port


def _iter_pcap(data: bytes):
    """Yield (ts_epoch, packet_bytes, l2_len) for a classic little/big-endian pcap."""
    if len(data) < 24:
        return
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):      # little-endian
        end = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):   # big-endian
        end = ">"
    else:
        raise SystemExit(f"not a pcap file (magic={magic.hex()})")
    nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    linktype = struct.unpack(end + "I", data[20:24])[0]
    l2_len = _L2_LEN.get(linktype, 14)
    off = 24
    while off + 16 <= len(data):
        ts_sec, ts_frac, incl, _orig = struct.unpack(end + "IIII", data[off:off + 16])
        off += 16
        pkt = data[off:off + incl]
        off += incl
        ts = ts_sec + (ts_frac / 1e9 if nano else ts_frac / 1e6)
        yield ts, pkt, l2_len


def _is_mod_export(pkt: bytes, l2_len: int) -> bool:
    """True only for a genuine outer MOD export (outer IPv4/UDP dport 31337),
    NOT an ICMP-unreachable reply that merely *quotes* a MOD packet."""
    ip = pkt[l2_len:]
    if len(ip) < 28 or (ip[0] >> 4) != 4:
        return False
    ihl = (ip[0] & 0x0F) * 4
    if ip[9] != 17:                       # outer must be UDP
        return False
    if len(ip) < ihl + 4:
        return False
    dport = int.from_bytes(ip[ihl + 2:ihl + 4], "big")
    return dport == _MOD_UDP_PORT


def _parse_embedded(pkt: bytes):
    """Return (src_ip, dst_ip, proto, sport, dport, qp) for the embedded dropped
    frame, or None if this packet has no IPv4 embed. `qp` is the RoCEv2 BTH
    destination QP when the embed is UDP/4791, else None."""
    idx = pkt.find(_MOD_RECORD_MARKER)
    if idx < 0:
        return None
    flen = int.from_bytes(pkt[idx + 6:idx + 8], "big")
    frame = pkt[idx + 8:idx + 8 + flen]
    if len(frame) < 14 + 20:
        return None
    ethertype = int.from_bytes(frame[12:14], "big")
    if ethertype != 0x0800:              # only IPv4 embeds (skip ARP etc.)
        return None
    ip = frame[14:]
    ihl = (ip[0] & 0x0F) * 4
    proto = ip[9]
    src_ip = ".".join(str(b) for b in ip[12:16])
    dst_ip = ".".join(str(b) for b in ip[16:20])
    sport = dport = 0
    qp = None
    if proto in (6, 17) and len(ip) >= ihl + 4:      # TCP / UDP
        sport = int.from_bytes(ip[ihl:ihl + 2], "big")
        dport = int.from_bytes(ip[ihl + 2:ihl + 4], "big")
        # RoCEv2 = UDP/4791 -> InfiniBand BTH; destination QP is BTH bytes 5..7.
        if proto == 17 and dport == _ROCE_UDP_PORT:
            bth = ip[ihl + 8:]           # UDP payload starts at the BTH
            if len(bth) >= 8:
                qp = (bth[5] << 16) | (bth[6] << 8) | bth[7]
    return src_ip, dst_ip, proto, sport, dport, qp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap", help="input pcap (MOD export capture on the collector)")
    ap.add_argument("--ingress", default="Ethernet72",
                    help="ingress port where the drop occurred (ACL bind port)")
    ap.add_argument("--egress", default="Ethernet0",
                    help="MOD mirror egress port")
    ap.add_argument("--reason", default="SAI_IN_DROP_REASON_ACL",
                    help="drop reason string (mapped by MODSource)")
    ap.add_argument("--queue", type=int, default=0)
    args = ap.parse_args()

    with open(args.pcap, "rb") as fh:
        data = fh.read()

    n_in = n_out = 0
    for ts, pkt, l2_len in _iter_pcap(data):
        n_in += 1
        if not _is_mod_export(pkt, l2_len):
            continue                       # skip ICMP replies / non-export frames
        parsed = _parse_embedded(pkt)
        if parsed is None:
            continue
        src_ip, dst_ip, proto, sport, dport, qp = parsed
        rec = {
            "ts": round(ts, 6),
            "ingress_port": args.ingress,
            "egress_port": args.egress,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "l4_proto": proto,
            "src_port": sport,
            "dst_port": dport,
            "qp_num": qp,
            "queue": args.queue,
            "drop_reason": args.reason,
            "count": 1,
        }
        sys.stdout.write(json.dumps(rec) + "\n")
        n_out += 1

    print(f"[pcap_to_mod_jsonl] read {n_in} frames, emitted {n_out} MOD drop events",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
