from dropscope import Correlator, DropEvent, EndpointRole
from dropscope.models import DropReason


def test_source_ip_attributes_to_sender(registry):
    c = Correlator(registry)
    ev = DropEvent(ts=1.0, ingress_port="Ethernet0", src_ip="10.0.1.5",
                   dst_ip="10.5.5.5", qp_num=1500, drop_reason=DropReason.WRED)
    ad = c.attribute(ev)
    assert ad.job_id == "job-a"
    assert ad.endpoint_role == EndpointRole.SENDER


def test_dest_ip_attributes_to_receiver(registry):
    c = Correlator(registry)
    ev = DropEvent(ts=1.0, ingress_port="Ethernet0", src_ip="10.9.9.9",
                   dst_ip="10.0.2.7", qp_num=2500)
    ad = c.attribute(ev)
    assert ad.job_id == "job-b"
    assert ad.endpoint_role == EndpointRole.RECEIVER


def test_unknown_traffic_is_unattributed(registry):
    c = Correlator(registry)
    ev = DropEvent(ts=1.0, ingress_port="Ethernet0", src_ip="10.8.8.8",
                   dst_ip="10.8.8.9")
    ad = c.attribute(ev)
    assert ad.job_id is None
    assert ad.endpoint_role == EndpointRole.UNKNOWN


def test_qp_gating_excludes_wrong_range(registry):
    # IP is in job-a's subnet, but QP is outside job-a's range -> no match.
    c = Correlator(registry)
    ev = DropEvent(ts=1.0, ingress_port="Ethernet0", src_ip="10.0.1.5",
                   dst_ip="10.7.7.7", qp_num=5000)
    ad = c.attribute(ev)
    assert ad.job_id is None


def test_flow_id_is_stable_and_qp_sensitive(registry):
    a = DropEvent(ts=1.0, ingress_port="e", src_ip="10.0.1.5", dst_ip="10.0.1.6",
                  src_port=40000, qp_num=1500)
    b = DropEvent(ts=2.0, ingress_port="e", src_ip="10.0.1.5", dst_ip="10.0.1.6",
                  src_port=40000, qp_num=1500)
    diff = DropEvent(ts=1.0, ingress_port="e", src_ip="10.0.1.5", dst_ip="10.0.1.6",
                     src_port=40000, qp_num=1600)
    assert a.flow_id() == b.flow_id()
    assert a.flow_id() != diff.flow_id()
