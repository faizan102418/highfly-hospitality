# Tenant, front-desk, and cloud staging readiness plan

**Candidate baseline:** `fedd26e9cc3a1eb09c0990749e18ee552b17ca3d`  
**Target:** cloud DEV/staging, first-client front desk, synthetic data only.  
**Current release status:** **NO-GO until the evidence gates below are completed.** Green CI/readiness checks are necessary but insufficient.

## 1. Baseline review

- CI runs API tests against PostgreSQL, a PostgreSQL smoke suite, SQLite migration compatibility, a disposable PostgreSQL backup/restore round trip, and a frontend production build.
- A live readiness workflow checks `https://highfly-hospitality-dev.onrender.com/api/ready` every six hours. It verifies HTTP 200 and the payload's `ready`/PostgreSQL mode; it does not test business routes or tenant boundaries.
- A staging blueprint exists at `render.staging.yaml` with a separate staging service/database. Its build command currently runs `alembic upgrade head`, and its auto-deploy trigger is commit. Treat provisioning/deployment and migrations as explicit operator actions; do not apply a migration or assume a staging environment is live from the YAML alone.
- Existing operational docs already describe front-desk acceptance, offline acceptance, production safety, and isolated recovery. Those procedures are instructions, not recorded successful drills.

## 2. Required code/CI gates

### Tenant isolation

- Test at least two organizations and two properties, including two properties under one organization.
- For each route family, exercise read, create, update, delete/void, idempotent replay, and cross-property source/destination references.
- Cover reservations, guests, rooms, room types, stays/occupants/rate segments, groups, folios/windows/items, payments/refunds, deposits/transfers, ledger transactions/entries, business-date/night-audit, expenses, restaurant POS, stock, suppliers/purchasing, housekeeping/maintenance, configuration, reports, and backup controls.
- For each denial, assert expected 401/403/404 and that row counts, room/stay/reservation state, folio balance, ledger balance, deposits, and successful business audit rows are unchanged.
- Route introspection must prove overlapping legacy and canonical routes resolve to the intended handler. Do not rely on source-level checks in only one module.

### Authentication and permissions

- Missing/invalid/expired tokens and deleted users return 401.
- Role permissions are read from current database state, not JWT claims.
- Property membership and active organization/property status are revalidated on every request that accesses tenant data.
- Least-privilege role matrix is explicit for front desk, housekeeping, finance/cashier, manager, and administrator.
- Bootstrap/admin setup is disabled after first setup and cannot be re-opened by a request race.
- Invalid input, denied operations, and failed transactions produce no partial business writes.
- Audit logs record actor, property, action, entity, reason/reference where required, and outcome without secrets or unnecessary guest ID-document data.

### Front-desk workflow and reconciliation

Use fictional guests and test IDs only. Record candidate SHA and exact test environment.

1. Create reservation → assign available clean room → confirm guest/property/room all match.
2. Check in → verify reservation/stay/room and check-in timestamp agree.
3. Repeat check-in and simulate retry after timeout → conflict/replay semantics are deterministic; no duplicate stay, financial transaction, deposit, folio item, or successful audit row.
4. Transfer room → reject dirty, out-of-order, occupied, and cross-property rooms without state changes.
5. Add room/other charges and deposits → compare folio, transaction, ledger, and deposit balances.
6. Apply a payment and a partial payment; test invalid, declined, overpayment, refund over limit, and unauthorized financial operation.
7. Verify debit/credit balance and the expected relationship between folio balance, posted payments, refunds, deposit liability/application, and ledger accounts. Do not assume the folio total alone proves reconciliation.
8. Attempt checkout with outstanding balance → reject atomically. Settle to zero, checkout, confirm folio closure, reservation/stay timestamps, room housekeeping state, and audit record.
9. Retry checkout → no duplicate financial or audit writes.
10. Complete housekeeping task and verify room availability only after required state transition.

The evidence template in `frontdesk-acceptance-evidence-template.md` is the record of truth. Every item must be pass/fail with expected and actual results; unknown means not passed.

## 3. Cloud DEV/staging setup and verification

### Configuration boundary

- Keep DEV and staging in separate services and separate PostgreSQL databases; do not reuse production credentials or databases.
- Use separate strong secrets and least-privilege credentials. Store secrets only in the hosting provider's secret store.
- Confirm HTTPS, health/readiness, database connectivity, service logs without credentials/guest data, and environment values before test data is entered.
- Staging must be populated only with synthetic records and must never be used for a production restore.
- Do not run `alembic upgrade head` manually against a live environment until the migration plan and target database are confirmed by the authorized operator.
- The checked-in Render blueprint is configuration-as-code; it does not prove the provider has provisioned the service, attached the intended database, or deployed this revision.

### Verification checklist

- [ ] Operator confirms a distinct staging web service and database exist.
- [ ] Record deployed commit SHA and Alembic revision without recording connection strings.
- [ ] Confirm staging `/api/health` and `/api/ready` return expected status and PostgreSQL mode.
- [ ] Confirm login, seeded synthetic tenant provisioning, and property membership work.
- [ ] Run the tenant-negative and front-desk workflow suite against staging only.
- [ ] Run the manual cloud acceptance checklist and save sanitized evidence.
- [ ] Confirm no production hostname/database/secret is referenced by staging.
- [ ] Verify rollback owner and the last known-good revision.
- [ ] Verify an encrypted synthetic staging backup artifact, manifest, and checksum.
- [ ] Restore into a separate isolated recovery database and compare revision, synthetic reservations/rooms, audit evidence, folio totals, and ledger balances.
- [ ] Record duration, checksum, restored revision, financial reconciliation, and defects.

## 4. Recovery boundary

Automated CI restore uses a disposable CI database and proves only that test path. A staging restore drill must use a staging backup and a distinct recovery database. A production backup/restore remains a separately approved operator task; nothing in this plan authorizes it.

Never copy production guest or financial data into staging. Never place database URLs, passwords, JWT secrets, tokens, or guest document values in issues, code, logs, screenshots, or chat.

## 5. Completion criteria

The release is GO only when the exact candidate SHA has green required CI, route/authorization regression coverage, the synthetic end-to-end front-desk workflow reconciles, the cloud staging endpoint is verified, and an isolated restore succeeds with recorded evidence. Until then, the status is NO-GO / evidence incomplete.
