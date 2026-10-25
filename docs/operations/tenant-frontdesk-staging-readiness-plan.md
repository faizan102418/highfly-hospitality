# Tenant, front-desk, and cloud staging readiness plan

**Target:** cloud staging; first-client scope = front desk; synthetic data only.  
**Current release status:** **NO-GO until the evidence gates below are completed.** Green CI/readiness checks are necessary but insufficient.

## 1. Baseline review

- CI runs API tests against PostgreSQL, PostgreSQL smoke tests, SQLite migration compatibility, a disposable PostgreSQL backup/restore round trip, and a frontend production build.
- A live readiness workflow checks the DEV readiness endpoint every six hours. It checks readiness/PostgreSQL mode; it does not test business routes or tenant boundaries.
- `render.staging.yaml` declares a staging service/database. The blueprint is configuration-as-code, not proof of provider provisioning or correct database attachment.
- Staging auto-deploy is disabled and the build command does not run migrations automatically. An authorized operator must provision/verify staging and explicitly approve deployment and migration steps.
- Existing operational docs and CI recovery tests are procedures/code checks, not evidence of a completed cloud acceptance or restore drill.

## 2. Tenant and authorization regression gates

Use at least two organizations and two properties, including two properties under one organization. For each relevant route family, exercise read, create, update, delete/void, idempotent replay, and cross-property source/destination references.

Cover reservations, guests, rooms, room types, stays/occupants/rate segments, groups, folios/windows/items, payments/refunds, deposits/transfers, ledger transactions/entries, business-date/night-audit, expenses, restaurant POS, stock, suppliers/purchasing, housekeeping/maintenance, configuration, reports, and backup controls. Include overlapping legacy/canonical routes.

For each denial, assert expected 401/403/404 and unchanged row counts, room/stay/reservation state, folio balance, ledger balance, deposits, and successful business audit rows. Current tests cover selected front-desk routes only; do not describe full route-family isolation as proven until systematic coverage exists.

Authentication checks must cover missing/invalid/expired tokens, deleted users, current database role permissions, property membership and active tenant state, and bootstrap being closed after setup. Denied operations and failed transactions must not leave partial writes. Audit logs must not expose secrets or unnecessary guest ID-document data.

## 3. Manual front-desk acceptance and reconciliation

Run against the verified staging service only, with fictional guests, synthetic IDs, synthetic amounts, and test-only role accounts. Record the candidate SHA, environment, tester, timestamps, expected/actual results, and sanitized evidence in `frontdesk-acceptance-evidence-template.md`.

1. Create reservation and assign an available clean room.
2. Check in; confirm reservation/stay/room linkage and timestamps.
3. Retry check-in, including timeout retry; verify no duplicate stay, financial transaction, deposit, folio item, or successful audit row.
4. Attempt cross-property access and invalid guest/room references; verify denial and no mutation.
5. Post charges, deposits, and payment; test idempotent replay, partial payment, invalid/declined/overpayment cases, and unauthorized financial actions as supported by the deployed UI.
6. Attempt checkout with outstanding balance; verify rejection is atomic.
7. Settle and checkout; retry checkout and verify no duplicate posting or transition.
8. Complete housekeeping and confirm room availability only after the required task/state transition.
9. Reconcile folio charges/credits/paid/balance against payments, refunds, deposits and ledger accounts. Verify ledger debit equals credit and record exact expected/actual amounts.
10. Verify retry/denial outcomes created no duplicate business or financial writes.

Unknown, unrun, or blocked means not passed. The evidence template is the record of truth.

## 4. Cloud staging verification

Before test data is entered:

- [ ] Provider control plane confirms staging service and separate PostgreSQL resource are provisioned.
- [ ] Database attachment and credentials are verified as staging-only, not DEV or production.
- [ ] Authorized operator approves deployment and any required migration after reviewing the exact target and migration plan.
- [ ] Record deployed commit SHA and Alembic revision without recording connection strings or secrets.
- [ ] Confirm HTTPS and staging `/api/health` and `/api/ready` return expected status and PostgreSQL mode.
- [ ] Confirm synthetic tenant provisioning, login, and property membership.
- [ ] Run tenant-negative and synthetic workflow tests against this exact staging candidate.
- [ ] Record manual acceptance evidence and defects.
- [ ] Confirm no production hostname/database/secret is referenced by staging.
- [ ] Record rollback owner, trigger, and last known-good revision.

## 5. Isolated recovery drill

A cloud staging restore drill is blocked until an authorized operator approves the staging backup source, isolated recovery target, timing, and procedure. Use only a synthetic staging backup and restore into a separate isolated recovery database—never production.

- [ ] Record artifact reference, manifest, checksum, and integrity result.
- [ ] Verify recovery target is separate from staging and production.
- [ ] Record restore duration and restored schema/Alembic revision.
- [ ] Compare pre/post synthetic reservations, stays, rooms, housekeeping tasks, folios, payments, audit evidence, and ledger entries.
- [ ] Reconcile folio totals and ledger debit/credit totals.
- [ ] Record defects/warnings and sanitized evidence.
- [ ] Operator and release owner review the result.

CI restore round trip is evidence for the disposable CI path only. It does not satisfy this cloud recovery gate.

## 6. Completion criteria

The release is GO only when the exact candidate SHA has green required CI, adequate route/authorization regression coverage, manual synthetic front-desk acceptance, exact financial/operational reconciliation, verified isolated staging configuration, and a successful isolated restore with recorded evidence. Until then, status is **NO-GO / evidence incomplete**.

This plan does not authorize deployment, live migrations, production data access, or production backup/restore. Those require separate explicit approval.
