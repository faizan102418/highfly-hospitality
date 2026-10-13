# Offline deployment and recovery runbook

This runbook is a deployment checklist, not proof that a particular laptop has passed an offline test. Complete and record the verification steps on the target machine before using the system for hotel operations.

## 1. Supported database modes

The API chooses its database from `HMS_DATABASE_URL` when configured. Without that setting, the current local fallback is SQLite at:

```text
<data checkout>/data/la_serene_hms.sqlite3
```

The data directory is created by the API database module relative to the repository checkout. Keep the database outside temporary folders and do not assume it is included in an application installer unless the installer explicitly includes it.

- **SQLite local mode:** a self-contained database file suitable for a single local installation. Keep the application and database on a local disk; do not place a live SQLite database on a network share.
- **PostgreSQL mode:** used when `HMS_DATABASE_URL` points to PostgreSQL. It requires a reachable PostgreSQL server. It is not standalone/offline merely because the web frontend is installed locally; the server must be reachable on the local network or same machine without internet.

Do not change database modes on an existing installation without a planned, verified migration. SQLite and PostgreSQL files are not interchangeable.

## 2. Prepare a laptop for offline use

1. Install the supported Python and Node.js versions, application dependencies, and any required browser/runtime components while connected to the internet.
2. Configure `HMS_SECRET_KEY` with a strong, installation-specific secret. Keep it private and do not store it in the repository.
3. Decide explicitly whether this installation uses local SQLite or a reachable local PostgreSQL server. Record the selected mode and the database location without recording credentials.
4. Start the API and frontend, complete initial administrator setup, and create only authorized user accounts. Do not use production credentials in a demo environment.
5. Confirm the health endpoint responds at `/api/health`, then sign in and perform the offline acceptance test below.
6. Disconnect internet access (but leave any required local loopback/LAN connection intact). Repeat the acceptance test. Internet disconnection alone does not prove that a remote database or third-party dependency is unnecessary.

## 3. Offline acceptance test

Use a disposable test installation and fictional data. Record the date, app commit/version, OS, database mode, tester, pass/fail, and any evidence location.

- [ ] Login and session behavior work without internet.
- [ ] Create/search a fictional guest and create a reservation.
- [ ] Check in, transfer a room, add folio charges, record a payment, and verify totals.
- [ ] Check out, confirm the room becomes dirty, and complete the housekeeping flow.
- [ ] Generate/print a receipt and the reports needed for the pilot.
- [ ] Verify an unauthorized role cannot perform restricted financial/admin actions.
- [ ] Stop and restart the app while still offline; confirm committed data remains.
- [ ] Simulate an invalid operation and verify no partial state or financial posting remains.
- [ ] Reconnect only after recording offline results; confirm the app resumes normally.

Do not mark a step passed based only on a successful CI run. Record actual laptop results. If any required operation needs the internet, document it as a limitation rather than claiming full offline support.

## 4. Local SQLite backup and isolated restore drill

Perform this drill with a disposable/demo database first. Do not restore over the live database.

1. Identify the exact SQLite file used by the running API; do not assume the current working directory is the data directory.
2. Stop the API cleanly before making a simple file copy, so no process is writing to the database. If the deployment cannot be stopped, use a SQLite-consistent backup procedure instead of copying a live file.
3. Copy the database to a restricted backup directory. Keep backups on a different physical device from the laptop when possible.
4. Calculate and record a SHA-256 checksum for the backup. Keep the checksum/manifest beside the backup, not embedded in the database.
5. Restore the copy to a separate recovery directory and point a separate, isolated app instance at that copy. Never point a restore drill at the original live database.
6. Verify the recovery instance starts, authenticates, and shows expected synthetic records. Compare reservation counts, folio balances, latest audit event, and business date against the source test instance.
7. Record backup/restore duration, checksum result, app revision, database mode, and discrepancies. Remove disposable recovery copies securely after the drill.

Example Windows PowerShell checksum command:

```powershell
Get-FileHash .\backup\la_serene_hms.sqlite3 -Algorithm SHA256
```

Example Linux checksum command:

```bash
sha256sum ./backup/la_serene_hms.sqlite3
```

A checksum verifies file integrity against the recorded value; it does not prove the backup is complete or restorable. Only the isolated restore and application-level checks establish that.

## 5. PostgreSQL backup and restore

For PostgreSQL installations, use the organization's approved `pg_dump` / `pg_restore` process and secure credential handling. Restore to a separate recovery database with a separate connection string. Verify the restored revision and application-level records before considering the drill successful.

Never put a database URL, password, access token, real guest details, or production financial data in GitHub issues, source files, terminal screenshots, or CI logs. Do not loosen production database network access just to make a backup workflow pass.

A production backup/restore drill is an operator-controlled activity requiring explicit approval, authorized credentials, and an isolated recovery target. It must not be run automatically against production by this documentation change.

## 6. Recovery and rollback checklist

- [ ] Stop the app before replacing local files or rolling back application binaries.
- [ ] Preserve the current database and logs securely before attempting recovery.
- [ ] Restore only to the intended target; verify its path/connection before starting the app.
- [ ] Start the app and verify health, login, business date, room/reservation state, and representative folio balances.
- [ ] Reconcile financial totals and audit events before resuming live operations.
- [ ] Record who performed the recovery, the approved backup used, checksum, duration, app revision, and outcome.
- [ ] Escalate discrepancies; do not improvise production data edits.

## 7. Current limitations and honest status

This repository's SQLite fallback makes a local database mode available, but it does not by itself prove that a packaged laptop deployment, all frontend assets, authentication/session behavior, printing, or every workflow operates without internet. This guide does not claim that offline acceptance, a full end-to-end front-desk rehearsal, or a production recovery drill has already passed.

No data synchronization between separate installations should be assumed unless a separately implemented and tested synchronization mechanism is documented.
