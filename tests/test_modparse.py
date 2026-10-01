"""Tests for the shared MOD IPFIX parser and the live UDP source."""

import struct

from dropscope.models import DropReason
from dropscope.modparse import MOD_RECORD_MARKER, parse_embedded
from dropscope.sources.mod_live import MODDatagramProtocol


def _ip2b(s):
    return bytes(int(x) for x in s.split("."))


def _ipv4(proto, src, dst, l4=b""):
    total = 20 + len(l4)
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, proto, 0,
                      _ip2b(src), _ip2b(dst))
    return hdr + l4


def _eth(payload, ethertype=0x0800):
    dst_mac = b"\x64\xac\x2b\x63\x54\x7f"
    src_mac = b"\x64\xac\x2b\x63\x81\x80"
    return dst_mac + src_mac + struct.pack("!H", ethertype) + payload


def _mod_export(frame):
    """Wrap an embedded L2 frame like a Broadcom MOD IPFIX export payload."""
    return b"\x00" * 28 + MOD_RECORD_MARKER + struct.pack("!H", len(frame)) + frame


def _icmp_frame(src="10.123.72.2", dst="10.99.0.1"):
    icmp = b"\x08\x00\x00\x00" + b"\x00" * 4          # echo request
    return _eth(_ipv4(1, src, dst, icmp))


def _roce_frame(qp, dst="10.0.1.23", src="10.123.72.2"):
    bth = bytes([0x64, 0x40, 0xff, 0xff, 0x00]) + qp.to_bytes(3, "big") \
        + bytes([0x80]) + (1).to_bytes(3, "big")
    udp = struct.pack("!HHHH", 34714, 4791, 8 + len(bth), 0) + bth
    return _eth(_ipv4(17, src, dst, udp))


def test_parse_icmp_embed():
    flow = parse_embedded(_mod_export(_icmp_frame()))
    assert flow is not None
    assert flow["src_ip"] == "10.123.72.2"
    assert flow["dst_ip"] == "10.99.0.1"
    assert flow["l4_proto"] == 1
    assert flow["qp_num"] is None


def test_parse_rocev2_bth_qp():
    flow = parse_embedded(_mod_export(_roce_frame(1487, dst="10.0.1.23")))
    assert flow is not None
    assert flow["dst_ip"] == "10.0.1.23"
    assert flow["l4_proto"] == 17
    assert flow["dst_port"] == 4791
    assert flow["qp_num"] == 1487


def test_no_marker_returns_none():
    assert parse_embedded(b"\x00" * 64) is None


def test_non_ipv4_embed_skipped():
    arp = _eth(b"\x00" * 28, ethertype=0x0806)
    assert parse_embedded(_mod_export(arp)) is None


def test_live_datagram_produces_event():
    got = []
    proto = MODDatagramProtocol(got.append, "Ethernet72", "Ethernet0",
                                "SAI_IN_DROP_REASON_ACL")
    proto.datagram_received(_mod_export(_roce_frame(2733, dst="10.0.2.51")),
                            ("10.123.0.1", 31337))
    assert len(got) == 1
    ev = got[0]
    assert ev.dst_ip == "10.0.2.51"
    assert ev.qp_num == 2733
    assert ev.dst_port == 4791
    assert ev.ingress_port == "Ethernet72"
    assert ev.egress_port == "Ethernet0"
    assert ev.drop_reason == DropReason.ACL_DENY


def test_live_datagram_ignores_junk():
    got = []
    proto = MODDatagramProtocol(got.append, "e", None, "ACL_ANY")
    proto.datagram_received(b"not a mod export at all", ("1.2.3.4", 1))
    assert got == []
