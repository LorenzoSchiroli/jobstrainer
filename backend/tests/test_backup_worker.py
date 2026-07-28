from unittest.mock import AsyncMock, patch

import pytest

from backend import backup as backup_mod


def test_to_libpq_url_strips_asyncpg_dialect():
    assert (
        backup_mod.to_libpq_url("postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer")
        == "postgresql://postgres:postgres@postgres:5432/jobstrainer"
    )


def test_to_libpq_url_leaves_plain_postgresql():
    assert (
        backup_mod.to_libpq_url("postgresql://postgres:postgres@localhost:5432/db")
        == "postgresql://postgres:postgres@localhost:5432/db"
    )


def test_validate_sbox_path_rejects_absolute():
    with pytest.raises(ValueError, match="relative"):
        backup_mod.validate_sbox_path("/backups/jobstrainer")


def test_validate_sbox_path_accepts_relative():
    backup_mod.validate_sbox_path("backups/jobstrainer")


def test_expired_backup_filenames_keeps_seven_newest():
    names = [
        f"jobstrainer-202607{day:02d}T020000Z.dump"
        for day in range(1, 11)
    ]
    expired = backup_mod.expired_backup_filenames(names, retain=7)
    assert expired == [
        "jobstrainer-20260703T020000Z.dump",
        "jobstrainer-20260702T020000Z.dump",
        "jobstrainer-20260701T020000Z.dump",
    ]


def test_expired_backup_filenames_ignores_non_matching():
    names = ["readme.txt", "jobstrainer-20260728T020000Z.dump"]
    assert backup_mod.expired_backup_filenames(names, retain=7) == []


def test_backup_configured_requires_all_sbox_env(monkeypatch):
    for key in (
        "DATABASE_URL",
        "BACKUP_SBOX_HOST",
        "BACKUP_SBOX_USER",
        "BACKUP_SBOX_RCLONE_PASS",
        "BACKUP_SBOX_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    assert backup_mod.backup_configured() is False

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")
    monkeypatch.setenv("BACKUP_SBOX_HOST", "u.your-storagebox.de")
    monkeypatch.setenv("BACKUP_SBOX_USER", "u")
    monkeypatch.setenv("BACKUP_SBOX_RCLONE_PASS", "obscured")
    monkeypatch.setenv("BACKUP_SBOX_PATH", "backups/jobstrainer")
    assert backup_mod.backup_configured() is True


async def test_run_backup_invokes_script_via_bash_when_configured(monkeypatch, tmp_path):
    # Not executable on purpose — worker must run via bash so Docker COPY
    # without +x still works.
    script = tmp_path / "postgres_backup.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o644)

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")
    monkeypatch.setenv("BACKUP_SBOX_HOST", "u.your-storagebox.de")
    monkeypatch.setenv("BACKUP_SBOX_USER", "u")
    monkeypatch.setenv("BACKUP_SBOX_RCLONE_PASS", "obscured")
    monkeypatch.setenv("BACKUP_SBOX_PATH", "backups/jobstrainer")

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("backend.backup.BACKUP_SCRIPT", script), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        await backup_mod.run_backup()

    mock_exec.assert_awaited_once()
    args = mock_exec.await_args.args
    assert args == ("bash", str(script))


async def test_run_backup_raises_when_script_fails(monkeypatch, tmp_path):
    script = tmp_path / "postgres_backup.sh"
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(0o644)

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")
    monkeypatch.setenv("BACKUP_SBOX_HOST", "u.your-storagebox.de")
    monkeypatch.setenv("BACKUP_SBOX_USER", "u")
    monkeypatch.setenv("BACKUP_SBOX_RCLONE_PASS", "obscured")
    monkeypatch.setenv("BACKUP_SBOX_PATH", "backups/jobstrainer")

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"boom"))

    with patch("backend.backup.BACKUP_SCRIPT", script), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        with pytest.raises(RuntimeError, match="boom"):
            await backup_mod.run_backup()
    assert mock_exec.await_args.args == ("bash", str(script))

async def test_backup_worker_exits_when_not_configured(monkeypatch):
    monkeypatch.delenv("BACKUP_SBOX_HOST", raising=False)
    with patch("backend.backup.run_backup", new_callable=AsyncMock) as mock_run:
        await backup_mod.backup_worker()
    mock_run.assert_not_awaited()
