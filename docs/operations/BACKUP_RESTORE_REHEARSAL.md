# PostgreSQL Backup and Restore Rehearsal

The repository helper is intentionally local-only. Use two fresh databases named
`phase10c_rehearsal_source` and `phase10c_rehearsal_target`. Migrate and seed the source,
then run:

```text
tools/postgres_backup_restore_rehearsal.sh backup --host localhost --port PORT --user USER --database phase10c_rehearsal_source --file /tmp/phase10c_rehearsal_TIMESTAMP.dump
tools/postgres_backup_restore_rehearsal.sh restore --host localhost --port PORT --user USER --database phase10c_rehearsal_target --file /tmp/phase10c_rehearsal_TIMESTAMP.dump
```

Verify Alembic head, IAM/link/session sentinels, pilot governance, marketplace records,
readiness and selected reads. Record duration as local evidence only, then delete the
artifact. It is not an RTO or RPO. Production backup/PITR needs a managed-provider owner,
retention/encryption policy, alerts and a separately approved restore procedure.
