# Production safety verification

This document records the safe verification sequence for the Render-hosted HMS. A green migration check is not a substitute for application health, tenant-isolation tests, or a restore drill.

## 1. Live service health

- Service URL: https://highfly-hospitality-dev.onrender.com
- Readiness endpoint: https://highfly-hospitality-dev.onrender.com/api/ready
- The readiness endpoint runs a database `SELECT 1` and should return HTTP 200 with `status: ready` and `mode: postgresql`.
- The repository workflow `Production readiness smoke check` checks the live endpoint on a six-hour schedule and can also be run manually from GitHub Actions.
- A passing endpoint confirms basic service/database reachability only. It does not prove all routes or tenant boundaries are correct.

### Verification status as of 2026-10-11

- Production migration alignment: **verified** by the successful read-only migration workflow. Database revision and code head both reported `0023_property_date_guards`.
- Live readiness after the latest deployment: **not verified from this session**. The public endpoint request could not be completed from the current execution environment; use the new GitHub Actions smoke check for a network path with public HTTPS access.
- Do not claim the latest Render deployment is healthy solely because the database migration check passed.

## 2. Tenant-isolation and financial-operation gate

Review each route independently, including legacy route modules that expose similar operations. A check in one endpoint does not secure another endpoint.

Minimum route families:
- Stay lookup, check-in, occupant changes, deposit listing/receipt/refund/application/transfer.
- New deposit transfer and its idempotent replay path.
- Folio integrity, reverse, correct, reconcile/reopen, payment/refund, invoice and ledger routes.
- Source and destination stays, folios, reservations, guests, rooms, and audit records must all resolve to the same authorized property where applicable.

Regression tests must use at least two properties and prove that a user assigned only to Property A cannot read or mutate Property B records. Test denied operations for no partial ledger writes, no partial deposit records, no unintended audit rows, and stable idempotency behavior.

### Current review gate — issue #11 reopened

Issue [#11](https://github.com/faizan102418/highfly-hospitality/issues/11) was reopened after reviewing the merged code and CI evidence. PR #30 merged to `main` at `68db72a2c93481745bea884050969bca83d1b316`; API and web jobs in CI run #449 passed, including the full unittest suite, PostgreSQL smoke tests, SQLite migration compatibility, and an isolated PostgreSQL backup/restore round trip. Windows deployment scripts workflow #449 also passed.

The remaining concern is financial consistency across overlapping legacy and completion deposit handlers. The legacy handlers in `phase_a_workflows.py` create deposit records/audit events but do not post the corresponding ledger transaction for receive/refund/apply, and legacy apply does not create a folio `Payment`; the completion handlers do. Route registration appears to put the completion router first, but this must be confirmed with route-introspection tests, and the legacy implementations must be made safe or removed/delegated so future route-order changes cannot expose inconsistent behavior. See [issue #11](https://github.com/faizan102418/highfly-hospitality/issues/11).

Do not call the security gate complete until route registration, balanced ledger/payment invariants, rollback/audit/idempotency behavior, and cross-property denial tests are verified on CI. This concern is not a confirmed production exploit. No production database operations were performed.

## 3. Backup and recovery

The repository includes a PostgreSQL backup tool under `ops/backup/backup.py` and a CI backup/restore round-trip test (`ops/backup/ci_roundtrip.py`). CI exercises a disposable database; it does not prove that a backup of the live Render database exists or that a production backup can be restored.

### Safe operator procedure

1. In Render, inspect the PostgreSQL database's available backup/PITR options and the current database plan/expiry. Do not assume the free plan provides a durable recovery guarantee.
2. Create a production backup using the approved operator process, with `HMS_DATABASE_URL` set in the operator's secure environment. Never paste the URL or password into chat, commit it, or put it in workflow logs.
3. Save the dump and its manifest in encrypted storage separate from the production database and the operator's laptop. Restrict access to the backup because it contains guest and financial data.
4. Verify the artifact checksum and manifest:
   ```bash
   python -m ops.backup.backup verify ./backups/FILE.dump ./backups/FILE.manifest.json
   ```
5. Restore only into a dedicated, isolated recovery database (never the production database):
   ```bash
   python -m ops.backup.backup restore-verify ./backups/FILE.dump ./backups/FILE.manifest.json --target-database-url "$HMS_RECOVERY_DATABASE_URL"
   ```
   The restore verifier uses `pg_restore --clean --if-exists` against the target database. Confirm the target URL is the disposable recovery database before running it.
6. Record the restore result, duration, restored Alembic revision, per-property business dates, and financial balance checks. Keep the recovery database isolated until validation is complete, then remove it using the operator's normal database lifecycle procedure.

### Verification status as of 2026-10-11

- Automated backup/restore round trip in CI: **implemented** in the CI workflow; a successful latest CI result must be inspected to call it passed.
- Live production backup artifact: **not verified** in this session.
- Restore of a live production backup into an isolated recovery database: **not performed** in this session.
- Do not run the CI helper against production: it creates and drops a database named `la_serene_hms_recovery_ci` and requires database-creation privileges.

## 4. Next operational module

No new module should be treated as ready to start until:
- the legacy financial/stay route authorization issue is resolved;
- two-property negative tests cover read and mutation attempts;
- ledger balance, deposit balance, rollback, audit and idempotency tests pass;
- the full API suite and PostgreSQL CI pass;
- the live readiness smoke check is green; and
- a production backup has been verified and a restore drill has succeeded.

Only then select the next module based on current roadmap and business priority.
