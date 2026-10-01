"""dropscope CLI — a SONiC-style ``show dropcounters`` for per-flow drop attribution.

Mirrors the sonic-utilities ``show`` UX (Click + tabulate). In sonic-utilities this
would register as ``show dropcounters flows|jobs|counts``; here the console entry is
``dropscope``, so you run ``dropscope show dropcounters flows``. It reads the live
dropscope API (default http://127.0.0.1:8000), so run ``make demo`` first.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import click
from tabulate import tabulate

DEFAULT_HOST = "http://127.0.0.1:8000"


def _get(host: str, path: str) -> dict:
    """GET a JSON object from the dropscope API."""
    url = host.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (localhost API)
        return json.loads(resp.read().decode())


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except urllib.error.URLError as exc:
        raise click.ClickException(
            f"cannot reach dropscope API ({exc.reason}). Is `make demo` running?"
        )


def _collect_flows(host: str, job: str | None = None, limit: int = 20) -> list[dict]:
    job_ids = [job] if job else [j["job_id"] for j in _get(host, "/api/jobs")["jobs"]]
    rows: list[dict] = []
    for jid in job_ids:
        data = _get(host, f"/api/jobs/{jid}/flows")
        name = data.get("name", jid)
        for flow in data.get("flows", []):
            rows.append(
                {
                    "job": name,
                    "flow": flow.get("flow_key") or flow.get("flow_id"),
                    "role": flow.get("role"),
                    "queue": flow.get("queue"),
                    "reason": flow.get("drop_reason"),
                    "drops": flow.get("drops", 0),
                }
            )
    rows.sort(key=lambda r: r["drops"], reverse=True)
    return rows[:limit]


def _render_flows(rows: list[dict]) -> str:
    table = [[r["job"], r["flow"], r["role"], r["queue"], r["reason"], r["drops"]] for r in rows]
    return tabulate(table, headers=["JOB", "FLOW", "ROLE", "QUEUE", "REASON", "DROPS"], tablefmt="simple")


def _render_jobs(data: dict) -> str:
    table = [[j["job_id"], j.get("name", j["job_id"]), j.get("drops", 0)] for j in data.get("jobs", [])]
    return tabulate(table, headers=["JOB ID", "NAME", "DROPS"], tablefmt="simple")


def _render_counts(data: dict) -> str:
    rows = sorted(data.get("by_reason", {}).items(), key=lambda kv: kv[1], reverse=True)
    return tabulate([[reason, n] for reason, n in rows], headers=["DROP REASON", "DROPS"], tablefmt="simple")


def _host_option(func):
    return click.option("--host", default=DEFAULT_HOST, show_default=True, help="dropscope API base URL")(func)


@click.group()
@click.version_option(package_name="dropscope")
def cli() -> None:
    """dropscope command-line interface."""


@cli.group()
def show() -> None:
    """Show dropscope state (SONiC show-style)."""


@show.group()
def dropcounters() -> None:
    """Per-flow / per-job drop attribution."""


@dropcounters.command()
@_host_option
@click.option("--job", default=None, help="limit to a single job id")
@click.option("--limit", default=20, show_default=True, help="max rows")
def flows(host: str, job: str | None, limit: int) -> None:
    """Top attributed flows — which flow and job each drop belongs to."""
    rows = _guard(_collect_flows, host, job, limit)
    click.echo(_render_flows(rows))


@dropcounters.command()
@_host_option
def jobs(host: str) -> None:
    """Per-job drop totals."""
    click.echo(_render_jobs(_guard(_get, host, "/api/jobs")))


@dropcounters.command()
@_host_option
def counts(host: str) -> None:
    """Per-reason drop counts (parallels ``show dropcounters counts``)."""
    click.echo(_render_counts(_guard(_get, host, "/api/summary")))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
