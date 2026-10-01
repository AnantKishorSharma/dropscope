from dropscope import Aggregator, Correlator, DropEvent
from dropscope.models import DropReason


def _drop(registry, src, dst, qp, ts, reason=DropReason.BUFFER_FULL, queue=3):
    ev = DropEvent(ts=ts, ingress_port="Ethernet0", src_ip=src, dst_ip=dst,
                   qp_num=qp, queue=queue, drop_reason=reason)
    return Correlator(registry).attribute(ev)


def test_totals_and_top_jobs(registry):
    agg = Aggregator(window_seconds=60)
    for i in range(5):
        agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 100 + i))
    agg.ingest(_drop(registry, "10.0.2.5", "10.0.2.6", 2500, 101))

    assert agg.total_drops == 6
    assert agg.by_job["job-a"] == 5
    assert agg.by_job["job-b"] == 1
    top = agg.top_jobs()
    assert top[0]["job_id"] == "job-a"
    assert top[0]["drops"] == 5


def test_series_sums_to_total(registry):
    agg = Aggregator(window_seconds=60, bucket_seconds=1)
    for i in range(4):
        agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 200 + i))
    total_in_series = sum(p["drops"] for p in agg.series())
    assert total_in_series == agg.total_drops == 4


def test_flows_for_job(registry):
    agg = Aggregator()
    agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 300))
    agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 301))
    flows = agg.flows_for_job("job-a")
    assert len(flows) == 1
    assert flows[0]["drops"] == 2
    assert flows[0]["role"] == "sender"


def test_window_eviction(registry):
    agg = Aggregator(window_seconds=10, bucket_seconds=1)
    agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 1000))
    agg.ingest(_drop(registry, "10.0.1.5", "10.0.1.6", 1500, 1100))  # 100s later
    # Old bucket evicted from the series; running totals still cumulative.
    assert all(p["ts"] >= 1100 - 10 for p in agg.series())
    assert agg.total_drops == 2
