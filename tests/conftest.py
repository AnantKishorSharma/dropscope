import pytest

from dropscope import JobRegistry


@pytest.fixture
def registry() -> JobRegistry:
    return JobRegistry.from_dict(
        {
            "jobs": [
                {"id": "job-a", "name": "A", "hosts": ["10.0.1.0/24"],
                 "qp_range": [1000, 1999]},
                {"id": "job-b", "name": "B", "hosts": ["10.0.2.0/24"],
                 "qp_range": [2000, 2999]},
            ]
        }
    )


@pytest.fixture
def scenario() -> dict:
    return {
        "duration_seconds": 10,
        "base_rate_pps": 10,
        "seed": 7,
        "fabric_ports": ["Ethernet0", "Ethernet8"],
        "unattributed_pool": "10.9.9.0/24",
        "phases": [
            {
                "name": "incast",
                "start": 0,
                "duration": 10,
                "rate_pps": 20,
                "weights": {"job-a": 8, "job-b": 1, "unattributed": 1},
                "reasons": {"BUFFER_FULL": 1},
                "queue": 3,
            }
        ],
    }
