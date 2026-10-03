# Local SQLite and private-asset recovery

The checked-in recovery utility is for local/demo SQLite installations. It uses SQLite's online backup API, checks database integrity, copies the private asset directory, and records SHA-256 hashes for every copied asset. Restore verifies the database and asset hashes and refuses to overwrite an existing destination. Keep backups access-controlled because they contain source and rendered media.

From `backend`, create a new destination directory for each backup:

```powershell
uv run python -m scripts.sqlite_recovery backup .\axiomweave.db .\.private-assets .\recovery\backup-2026-10-03
uv run python -m scripts.sqlite_recovery restore .\recovery\backup-2026-10-03 .\recovery\restore-drill-2026-10-03
```

After restore, point a local test instance at the restored database and private asset directory, check `/api/health/ready`, and verify owner-scoped source/media previews. Do not restore over a live database. PostgreSQL deployments need a separately operated PostgreSQL backup/restore procedure; this SQLite helper is not a PostgreSQL backup tool.

Recovery validation is exercised in `backend/tests/test_recovery.py`. It checks database integrity, source and rendered asset references, file hashes, overwrite refusal, and rejection of a corrupted backup. The durable job recovery/retry path remains covered by `backend/tests/test_phase4_worker_recovery.py` and the Phase-5 media retry tests. Automated checks do not replace a production restore drill.
