#!/usr/bin/env bash
# bash (not dash): need pipefail so a failed rclone lsf cannot silently skip retention.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_SBOX_HOST:?BACKUP_SBOX_HOST is required}"
: "${BACKUP_SBOX_USER:?BACKUP_SBOX_USER is required}"
: "${BACKUP_SBOX_RCLONE_PASS:?BACKUP_SBOX_RCLONE_PASS is required}"
: "${BACKUP_SBOX_PATH:?BACKUP_SBOX_PATH is required}"

# SQLAlchemy dialect URLs are not libpq URIs.
pg_url="$(printf '%s' "${DATABASE_URL}" | sed 's|postgresql+asyncpg://|postgresql://|')"

case "${BACKUP_SBOX_PATH}" in
  /*)
    echo "BACKUP_SBOX_PATH must be relative (no leading /) for Hetzner Storage Box" >&2
    exit 1
    ;;
esac

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
filename="jobstrainer-${timestamp}.dump"
dump_path="${work_dir}/${filename}"
config_path="${work_dir}/rclone.conf"
listing_path="${work_dir}/listing.txt"

# Hetzner Storage Box listens on 23; override for local smoke tests.
port="${BACKUP_SBOX_PORT:-23}"

cat > "${config_path}" <<EOF
[storagebox]
type = sftp
host = ${BACKUP_SBOX_HOST}
port = ${port}
user = ${BACKUP_SBOX_USER}
pass = ${BACKUP_SBOX_RCLONE_PASS}
shell_type = none
EOF

pg_dump --format=custom --file="${dump_path}" "${pg_url}"
rclone --config "${config_path}" copyto "${dump_path}" "storagebox:${BACKUP_SBOX_PATH}/${filename}"

# rclone lsf has no --sort flag. Filenames sort lexicographically by timestamp.
# Materialize the listing first so a failed remote list aborts before any delete.
rclone --config "${config_path}" lsf --files-only --format p \
  "storagebox:${BACKUP_SBOX_PATH}" > "${listing_path}"

# grep exits 1 when nothing matches (fewer than eight dumps); that is not a failure.
grep -E '^jobstrainer-[0-9]{8}T[0-9]{6}Z\.dump$' "${listing_path}" \
  | sort -r \
  | awk 'NR > 7 { print }' \
  > "${work_dir}/expired.txt" || true

while IFS= read -r expired; do
  rclone --config "${config_path}" deletefile "storagebox:${BACKUP_SBOX_PATH}/${expired}"
done < "${work_dir}/expired.txt"
