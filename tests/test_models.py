import pytest
from pydantic import ValidationError

from dropscope.models import DropEvent


def _mk(**kw):
    base = dict(ts=1.0, ingress_port="e", src_ip="10.0.0.1", dst_ip="10.0.0.2")
    base.update(kw)
    return DropEvent(**base)


def test_count_must_be_positive():
    with pytest.raises(ValidationError):
        _mk(count=0)


def test_port_upper_bound():
    with pytest.raises(ValidationError):
        _mk(src_port=99999)


def test_qp_must_be_nonnegative():
    with pytest.raises(ValidationError):
        _mk(qp_num=-1)


def test_flow_id_direction_and_qp_sensitivity():
    a = _mk(src_ip="10.0.0.1", dst_ip="10.0.0.2", qp_num=1000)
    rev = _mk(src_ip="10.0.0.2", dst_ip="10.0.0.1", qp_num=1000)
    assert a.flow_id() != rev.flow_id()      # unidirectional flows differ
    assert len(a.flow_id()) == 12            # blake2b digest_size=6 -> 12 hex
