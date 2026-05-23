#!/usr/bin/env python3
"""
Diagnostic CLI: prints N random jobs from Postgres + their OpenSearch documents.

Usage (from repo root):
    uv run --package backend python inspect_data.py
    uv run --package backend python inspect_data.py --n 5
    uv run --package backend python inspect_data.py --id <job-uuid>
"""
import argparse
import asyncio
import json
import textwrap
import urllib.request
from uuid import UUID

import asyncpg

PG_DSN = "postgresql://postgres:postgres@localhost:5432/jobstrainer"
OS_URL = "http://localhost:9200"
DESCRIPTION_MAX = 300


def _os_get(path: str) -> dict:
    with urllib.request.urlopen(f"{OS_URL}{path}") as r:
        return json.loads(r.read())


def _os_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OS_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _sep(title: str = "", width: int = 80) -> None:
    if title:
        pad = max(0, width - len(title) - 4)
        print(f"\n{'─' * 2} {title} {'─' * pad}")
    else:
        print("─" * width)


def _field(label: str, value) -> None:
    if value is None:
        print(f"  {label:<30} (null)")
    elif isinstance(value, str) and len(value) > DESCRIPTION_MAX:
        short = textwrap.shorten(value, width=DESCRIPTION_MAX, placeholder=" …")
        print(f"  {label:<30} {short}")
    elif isinstance(value, (dict, list)):
        print(f"  {label:<30} {json.dumps(value, ensure_ascii=False)}")
    else:
        print(f"  {label:<30} {value}")


def print_pg_job(job: dict, company: dict) -> None:
    _sep("POSTGRES — job")
    for k, v in job.items():
        _field(k, v)
    _sep("POSTGRES — company")
    for k, v in company.items():
        _field(k, v)


def print_os_doc(doc: dict | None) -> None:
    _sep("OPENSEARCH — document")
    if doc is None:
        print("  (not found)")
        return
    for k, v in doc.items():
        if k == "embedding":
            dim = len(v) if isinstance(v, list) else "?"
            print(f"  {'embedding':<30} [{dim}-dim vector, hidden]")
        elif k == "description":
            _field(k, v)
        else:
            _field(k, v)


async def fetch_jobs(conn: asyncpg.Connection, n: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT j.*, row_to_json(c)::text AS company_json
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        ORDER BY random()
        LIMIT $1
        """,
        n,
    )


async def fetch_job_by_id(conn: asyncpg.Connection, job_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT j.*, row_to_json(c)::text AS company_json
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.id = $1
        """,
        job_id,
    )


def os_fetch(job_id: str) -> dict | None:
    try:
        resp = _os_post(
            "/jobs/_search",
            {"query": {"term": {"job_id": job_id}}, "_source": True, "size": 1},
        )
        hits = resp["hits"]["hits"]
        return hits[0]["_source"] if hits else None
    except Exception as e:
        return {"error": str(e)}


def record_to_dict(row: asyncpg.Record) -> tuple[dict, dict]:
    job = dict(row)
    company = json.loads(job.pop("company_json"))
    job = {k: (str(v) if isinstance(v, UUID) else v) for k, v in job.items()}
    return job, company


async def main(n: int, job_id: str | None) -> None:
    conn = await asyncpg.connect(PG_DSN)
    try:
        if job_id:
            row = await fetch_job_by_id(conn, UUID(job_id))
            rows = [row] if row else []
        else:
            rows = await fetch_jobs(conn, n)
    finally:
        await conn.close()

    if not rows:
        print("No records found.")
        return

    total_pg = await asyncpg.connect(PG_DSN)
    pg_count = await total_pg.fetchval("SELECT count(*) FROM jobs")
    await total_pg.close()

    try:
        os_count = _os_get("/jobs/_count").get("count", "?")
    except Exception:
        os_count = "unreachable"

    print(f"\nPostgres jobs: {pg_count}   OpenSearch docs: {os_count}")
    _sep(width=80)

    for i, row in enumerate(rows, 1):
        job, company = record_to_dict(row)
        print(f"\n{'═' * 80}")
        print(f"  Record {i}/{len(rows)}  —  job_id: {job['id']}")
        print(f"{'═' * 80}")
        print_pg_job(job, company)
        os_doc = os_fetch(job["id"])
        print_os_doc(os_doc)

    print(f"\n{'═' * 80}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Postgres + OpenSearch job records")
    parser.add_argument("--n", type=int, default=3, help="Number of random records to show (default: 3)")
    parser.add_argument("--id", dest="job_id", default=None, help="Inspect a specific job by UUID")
    args = parser.parse_args()
    asyncio.run(main(args.n, args.job_id))
