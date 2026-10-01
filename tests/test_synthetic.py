from collections import Counter

from dropscope import Correlator, DropEvent
from dropscope.sources.synthetic import SyntheticSource


def test_generation_is_nonempty_and_typed(registry, scenario):
    events = SyntheticSource(registry, scenario).generate()
    assert len(events) > 0
    assert all(isinstance(e, DropEvent) for e in events)


def test_generation_is_deterministic(registry, scenario):
    a = SyntheticSource(registry, scenario).generate()
    b = SyntheticSource(registry, scenario).generate()
    assert [e.flow_key() for e in a] == [e.flow_key() for e in b]


def test_incast_concentrates_on_target_job(registry, scenario):
    events = SyntheticSource(registry, scenario).generate()
    c = Correlator(registry)
    counts = Counter((c.attribute(e).job_id or "unattributed") for e in events)
    # job-a is weighted 8x vs others in the incast phase.
    assert counts["job-a"] > counts["job-b"]
    assert counts["job-a"] > counts["unattributed"]
