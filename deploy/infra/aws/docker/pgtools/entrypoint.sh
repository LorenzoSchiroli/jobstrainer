#!/usr/bin/env bash
# Dump or restore RDS via S3 staging. Modes: dump | restore
set -euo pipefail

mode="${1:-}"
if [[ "${mode}" != "dump" && "${mode}" != "restore" ]]; then
  echo "usage: entrypoint.sh dump|restore" >&2
  exit 2
fi

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${DUMP_S3_URI:?DUMP_S3_URI is required}"

# App secret uses SQLAlchemy async URL; libpq wants postgresql://
PGURL="${DATABASE_URL/+asyncpg/}"
LOCAL_DUMP="/tmp/jobstrainer.dump"

if [[ "${mode}" == "dump" ]]; then
  echo "==> pg_dump -Fc → ${LOCAL_DUMP}"
  pg_dump -Fc --no-owner --no-acl "${PGURL}" -f "${LOCAL_DUMP}"
  echo "==> aws s3 cp → ${DUMP_S3_URI}"
  aws s3 cp "${LOCAL_DUMP}" "${DUMP_S3_URI}"
  echo "dump complete"
  exit 0
fi

echo "==> aws s3 cp ← ${DUMP_S3_URI}"
aws s3 cp "${DUMP_S3_URI}" "${LOCAL_DUMP}"

echo "==> pg_restore --clean --if-exists --no-owner"
set +e
pg_restore --clean --if-exists --no-owner -d "${PGURL}" "${LOCAL_DUMP}"
rc=$?
set -e

if [[ "${rc}" -gt 1 ]]; then
  echo "error: pg_restore failed with exit ${rc}" >&2
  exit "${rc}"
fi

if ! psql "${PGURL}" -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM jobs LIMIT 1" >/dev/null; then
  echo "error: restore finished but jobs table is not queryable" >&2
  exit 1
fi

if [[ "${rc}" -eq 1 ]]; then
  echo "warning: pg_restore reported warnings (exit 1); continuing after jobs check" >&2
fi

echo "restore complete"
