import json

from dropscope.models import DropEvent, DropReason
from dropscope.sources.mod import MODSource, map_reason, normalize


def test_normalize_maps_fields_and_reason():
    rec = {
        "ts": 5.0, "ingress_port": "Ethernet0", "src_ip": "10.0.1.5",
        "dst_ip": "10.0.1.6", "qp_num": 1500, "queue": 3,
        "drop_reason": "SAI_OUT_DROP_REASON_EGRESS_BUFFER_FULL",
    }
    ev = normalize(rec)
    assert isinstance(ev, DropEvent)
    assert ev.qp_num == 1500
    assert ev.drop_reason == DropReason.BUFFER_FULL


def test_unknown_reason_degrades_gracefully():
    assert map_reason("SOMETHING_BRAND_NEW") == DropReason.UNKNOWN
    assert map_reason(None) == DropReason.UNKNOWN


def test_real_th5_reason_names_are_mapped():
    # names as advertised by `show dropcounters capabilities` on the TH5 DUT
    assert map_reason("EXCEEDS_L3_MTU") == DropReason.MTU_EXCEEDED
    assert map_reason("ACL_ANY") == DropReason.ACL_DENY
    assert map_reason("INGRESS_VLAN_FILTER") == DropReason.INGRESS_VLAN
    assert map_reason("L3_EGRESS_LINK_DOWN") == DropReason.L3_NO_ROUTE
    assert map_reason("TTL") == DropReason.UNKNOWN  # unmapped -> graceful


def test_live_switch_and_port_stat_names_are_mapped():
    # real COUNTERS_DB stat names streamed by the live DUT bridge
    assert map_reason("SAI_SWITCH_STAT_PACKET_INTEGRITY_DROP") == DropReason.PACKET_INTEGRITY
    assert map_reason("SAI_PORT_STAT_IF_IN_DISCARDS") == DropReason.PORT_DISCARD
    assert map_reason("SAI_PORT_STAT_IF_OUT_DISCARDS") == DropReason.PORT_DISCARD


def test_replay_skips_malformed_records(tmp_path):
    p = tmp_path / "cap.jsonl"
    p.write_text("\n".join([
        json.dumps({"ts": 1.0, "ingress_port": "e", "src_ip": "10.0.1.5",
                    "dst_ip": "10.0.1.6", "qp_num": 1500}),
        "{ this is not valid json",
        json.dumps({"ts": 3.0, "ingress_port": "e", "src_ip": "10.0.1.7",
                    "dst_ip": "10.0.1.8", "queue": -5}),  # invalid -> skipped
        "",
    ]))
    events = list(MODSource(str(p)).events())
    srcs = [e.src_ip for e in events]
    assert "10.0.1.5" in srcs           # valid record survives
    assert "10.0.1.7" not in srcs       # invalid queue record skipped, no crash
    assert all(isinstance(e, DropEvent) for e in events)
