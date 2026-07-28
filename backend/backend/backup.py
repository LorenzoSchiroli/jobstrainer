"""Nightly Postgres backup loop: pg_dump + rclone upload to Hetzner Storage Box."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL_SECONDS", "86400"))
BACKUP_RETENTION_COUNT = 7
BACKUP_SCRIPT = Path(__file__).resolve().parent / "scripts" / "postgres_backup.sh"
_DUMP_NAME_RE = re.compile(r"^jobstrainer-\d{8}T\d{6}Z\.dump$")

_REQUIRED_ENV = (
    "DATABASE_URL",
    "BACKUP_SBOX_HOST",
    "BACKUP_SBOX_USER",
    "BACKUP_SBOX_RCLONE_PASS",
    "BACKUP_SBOX_PATH",
)


def to_libpq_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def validate_sbox_path(path: str) -> None:
    if path.startswith("/"):
        raise ValueError(
            "BACKUP_SBOX_PATH must be relative (no leading /) for Hetzner Storage Box"
        )


def expired_backup_filenames(names: list[str], retain: int = BACKUP_RETENTION_COUNT) -> list[str]:
    matching = sorted((n for n in names if _DUMP_NAME_RE.match(n)), reverse=True)
    return matching[retain:]


def backup_configured() -> bool:
    return all(os.environ.get(key) for key in _REQUIRED_ENV)


async def run_backup() -> None:
    if not backup_configured():
        raise RuntimeError("Backup env is incomplete")
    validate_sbox_path(os.environ["BACKUP_SBOX_PATH"])
    if not BACKUP_SCRIPT.is_file():
        raise FileNotFoundError(f"Backup script missing: {BACKUP_SCRIPT}")

    env = os.environ.copy()
    env["DATABASE_URL"] = to_libpq_url(env["DATABASE_URL"])

    # Invoke via bash so the script need not be +x (Docker COPY can drop mode).
    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(BACKUP_SCRIPT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"postgres_backup.sh failed ({proc.returncode}): {stderr.decode().strip()}"
        )
    logger.info("Postgres backup uploaded successfully")


async def backup_worker() -> None:
    if not backup_configured():
        logger.info("Postgres backup disabled (BACKUP_SBOX_* unset)")
        return
    while True:
        try:
            await run_backup()
        except Exception as e:
            logger.warning("Backup worker error: %s", e)
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
