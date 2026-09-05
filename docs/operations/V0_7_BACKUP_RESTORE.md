# Interest Growth v0.7 — Backup / Restore Contract (Gate A)

The server persistent unit is one consistency unit. This contract defines
what a valid backup is, how to create it, and how to prove a restore.

## 1. Persistent unit

```text
server data (persistent volume)
├── psychology_growth.db     canonical database (SQLite, single writer)
├── sources/                 canonical Source originals
├── artifacts/               exported/generated product files
└── (backup metadata lives inside each backup bundle)
```

A backup is complete only when the database and **both** vaults come from one
consistent backup operation. Copying a live SQLite file alone is never a
backup.

## 2. Backup bundle layout

```text
backup-<utc-timestamp>/
├── manifest.json           schema/app version, checksums, created_at
├── psychology_growth.db    consistent SQLite snapshot (backup API, not file copy)
├── sources/                full copy of the Source vault
└── artifacts/              full copy of the Artifact vault
```

`manifest.json` shape:

```json
{
  "product": "interest-growth",
  "server_version": "0.7.0",
  "schema_version": 16,
  "server_instance_id": "<uuid>",
  "created_at": "…",
  "database": {"file": "psychology_growth.db", "sha256": "…"},
  "sources": {"sha256": "…"},
  "artifacts": {"sha256": "…"},
  "file_count": {"sources": 0, "artifacts": 0}
}
```

Checksums are computed over the copied file trees so a partially written
bundle is detectable before any restore attempt.

## 3. Creating a backup

1. The API process is the single writer. Backups use the SQLite online
   backup API for a consistent database snapshot instead of copying a live
   file.
2. Backups take the exclusive maintenance/write lock, which drains application
   vault writes for the whole DB + vault copy span (an in-process reader/writer
   gate plus a cross-process advisory flock). The database snapshot is taken
   first, then Source and Artifact vaults are copied under the same lock, so
   the three parts represent one consistent moment. Checksums still detect
   bundle corruption.
3. Backups are written into a declared backup volume/directory, never into
   the live data volume paths.
4. An operator may run backups manually (`scripts/backup_server.py`) or from
   a scheduled job; the same bundle format is used in Docker.

## 4. Restoring a backup

1. Restore takes the exclusive maintenance/write lock and uses a staged,
   rollback-safe sequence: the bundle is copied to temporary paths and fully
   verified there before the live DB + Sources + Artifacts are switched. The
   previous live state is retained as `*.pre-restore-<ts>` until post-restore
   checks pass, so any failure leaves the original live state recoverable.
2. Validate the manifest checksums before touching the live paths.
3. Start the restored database, re-run migrations from the frozen schema
   version to the current one, then verify:
   - `PRAGMA foreign_key_check` reports no violations;
   - representative integrity checks on product tables pass;
   - every `sources.local_file` reference exists in the restored vault and
     every stored artifact key resolves under the artifact root.
4. Exercise representative reads/downloads after restore.
5. `scripts/restore_server.py --verify-only` runs all checks against the
   bundle without modifying live data.

## 5. Verification requirements (tests)

- Backup of a quiesced database with product data produces a manifest with
  valid checksums.
- Online backup coordinates DB and vault mutations under one maintenance/write
  lock; a concurrent-write regression test passes.
- Restore into a clean data directory passes integrity + reference checks.
- Restoring an older schema version upgrades to the current version through
  the normal migration path.
- Checksum mismatch is detected and blocks restore.
- Vault file references in restored data resolve to the restored files.
