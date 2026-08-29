#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 backup|restore --host localhost --port PORT --user USER --database phase10c_rehearsal_NAME --file PATH"
}

[[ $# -eq 11 ]] || { usage; exit 2; }
action=$1
[[ $2 == "--host" && $4 == "--port" && $6 == "--user" && $8 == "--database" && ${10} == "--file" ]] || { usage; exit 2; }
host=$3
port=$5
user=$7
database=$9
artifact=${11}

# This repository helper is deliberately incapable of targeting remote/production DBs.
[[ $host == "localhost" || $host == "127.0.0.1" ]] || {
  echo "restore rehearsal is restricted to localhost" >&2
  exit 2
}
[[ $database == phase10c_rehearsal_* ]] || {
  echo "database name must carry the phase10c_rehearsal_ safety marker" >&2
  exit 2
}
[[ $artifact == /tmp/phase10c_rehearsal_* ]] || {
  echo "artifact must be an explicit task-scoped file under /tmp" >&2
  exit 2
}

case $action in
  backup)
    [[ ! -e $artifact ]] || { echo "refusing to overwrite backup artifact" >&2; exit 2; }
    pg_dump --format=custom --no-owner --no-acl --host="$host" --port="$port" --username="$user" --dbname="$database" --file="$artifact"
    ;;
  restore)
    [[ -f $artifact ]] || { echo "backup artifact not found" >&2; exit 2; }
    pg_restore --exit-on-error --no-owner --no-acl --host="$host" --port="$port" --username="$user" --dbname="$database" "$artifact"
    ;;
  *) usage; exit 2 ;;
esac
