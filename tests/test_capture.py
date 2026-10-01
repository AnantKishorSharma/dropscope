import collections
from pathlib import Path

from dropscope import Correlator, JobRegistry
from dropscope.aggregate import Aggregator
from dropscope.sources.mod import MODSource

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "captures" / "th5-ug-seed.jsonl"
JOBS = ROOT / "config" / "jobs.example.yaml"


def test_dut_capture_parses_and_attributes():
    assert CAPTURE.exists(), "run scripts/make_th5_capture.py to generate it"
    reg = JobRegistry.from_yaml(str(JOBS))
    cor, agg = Correlator(reg), Aggregator()
    reasons = collections.Counter()
    n = 0
    for ev in MODSource(str(CAPTURE)).events():
        agg.ingest(cor.attribute(ev))
        reasons[ev.drop_reason.value] += 1
        n += 1

    assert n >= 40                          # provenance comment lines skipped
    assert agg.top_jobs()[0]["job_id"] == "job-alpha"   # incast weighting holds
    # real TH5 reason names were mapped (not everything degraded to UNKNOWN)
    assert reasons["MTU_EXCEEDED"] > 0 or reasons["ACL_DENY"] > 0
    # every attributed alpha flow is a RoCEv2 (UDP/4791) 5-tuple with a QP
    flows = agg.flows_for_job("job-alpha")
    assert flows and "4791" in flows[0]["flow_key"] and "#qp" in flows[0]["flow_key"]
