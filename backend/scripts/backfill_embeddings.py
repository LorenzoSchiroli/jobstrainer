"""One-time backfill: recompute embeddings for jobs whose Postgres `embedding`
column is empty (they predate storing embeddings in Postgres).

Run from the backend/ directory:
    uv run python scripts/backfill_embeddings.py

Delete this script once it has been run successfully against production data.
"""
import asyncio

from sqlalchemy import select

from backend.database import get_session_factory
from backend.models import Job, Outbox
from backend.search.models_lifecycle import init_models, get_biencoder


def _flatten_summary(summary: dict | None) -> str:
    if not summary:
        return ""
    parts = (
        summary.get("role_info", []) +
        summary.get("requirements", []) +
        summary.get("responsibilities", []) +
        summary.get("domain", [])
    )
    return " ".join(parts)


async def backfill(batch_size: int = 100) -> None:
    init_models()
    model = get_biencoder()
    factory = get_session_factory()

    async with factory() as session:
        result = await session.execute(select(Job).where(Job.embedding.is_(None)))
        jobs = result.scalars().all()
        print(f"Found {len(jobs)} jobs missing embeddings")

        updated = 0
        skipped = 0
        for job in jobs:
            text = _flatten_summary(job.summary)
            if not text.strip():
                skipped += 1
                continue
            job.embedding = model.encode(f"{job.title}\n{text}").tolist()
            session.add(Outbox(event_type="job_upserted", entity_id=job.id))
            updated += 1
            if updated % batch_size == 0:
                await session.commit()
                print(f"Committed {updated} so far...")

        await session.commit()
        print(f"Done. Updated {updated} jobs, skipped {skipped} with no summary text.")


if __name__ == "__main__":
    asyncio.run(backfill())
