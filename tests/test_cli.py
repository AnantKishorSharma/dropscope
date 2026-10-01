"""Tests for the ``dropscope show dropcounters`` CLI."""

from __future__ import annotations

import urllib.error

import pytest
from click.testing import CliRunner

import dropscope.cli as climod


def _fake_get(host, path):
    if path == "/api/jobs":
        return {
            "jobs": [
                {"job_id": "job-alpha", "name": "LLM pretrain (alpha)", "drops": 42},
                {"job_id": "unattributed", "name": "unattributed", "drops": 5},
            ]
        }
    if path.endswith("/flows"):
        job_id = path.split("/")[3]
        if job_id == "job-alpha":
            return {
                "job_id": "job-alpha",
                "name": "LLM pretrain (alpha)",
                "flows": [
                    {
                        "flow_id": "f1",
                        "flow_key": "10.0.1.11:34714->10.0.1.23:4791",
                        "role": "source",
                        "queue": 0,
                        "drop_reason": "ACL_ANY",
                        "drops": 30,
                    }
                ],
            }
        return {"job_id": job_id, "name": job_id, "flows": []}
    if path == "/api/summary":
        return {"total_drops": 47, "by_reason": {"ACL_ANY": 30, "TTL": 12, "IP_HEADER_ERROR": 5}}
    raise AssertionError(f"unexpected path {path}")


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(climod, "_get", _fake_get)
    return CliRunner()


def test_jobs(runner):
    result = runner.invoke(climod.cli, ["show", "dropcounters", "jobs"])
    assert result.exit_code == 0
    assert "job-alpha" in result.output
    assert "LLM pretrain (alpha)" in result.output
    assert "DROPS" in result.output


def test_flows(runner):
    result = runner.invoke(climod.cli, ["show", "dropcounters", "flows"])
    assert result.exit_code == 0
    assert "10.0.1.11:34714->10.0.1.23:4791" in result.output
    assert "LLM pretrain (alpha)" in result.output
    assert "ACL_ANY" in result.output


def test_flows_single_job(runner):
    result = runner.invoke(climod.cli, ["show", "dropcounters", "flows", "--job", "job-alpha"])
    assert result.exit_code == 0
    assert "10.0.1.11:34714->10.0.1.23:4791" in result.output


def test_counts(runner):
    result = runner.invoke(climod.cli, ["show", "dropcounters", "counts"])
    assert result.exit_code == 0
    assert "ACL_ANY" in result.output
    assert "DROP REASON" in result.output


def test_flows_unreachable(monkeypatch):
    def boom(host, path):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(climod, "_get", boom)
    result = CliRunner().invoke(climod.cli, ["show", "dropcounters", "flows"])
    assert result.exit_code != 0
    assert "cannot reach dropscope API" in result.output
