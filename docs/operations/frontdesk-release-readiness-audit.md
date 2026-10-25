# Front-desk release-readiness audit

**Scope:** cloud deployment candidate; first client = front desk; synthetic data only.  
**Status:** **NO-GO / external evidence incomplete** until required CI, staging, manual acceptance, and recovery checks are recorded against the exact candidate SHA.

## Baseline and automated evidence

The repository currently contains PostgreSQL API tests, PostgreSQL smoke tests, SQLite migration compatibility checks, a disposable-PostgreSQL backup/restore round trip, and a frontend production build. The merged front-desk regression work adds bootstrap concurrency coverage, property-scoped guest duplicate matching, cross-property denial tests for selected front-desk operations, and a synthetic PostgreSQL lifecycle/reconciliation test.

These are useful code-level checks, not proof that the deployed cloud service is isolated or that every legacy/canonical route family is tenant-safe. CI's restore round trip uses a disposable CI database; it is not a cloud staging restore drill.

## Staging configuration boundary

The checked-in `render.staging.yaml` declares a staging web service and a separately named PostgreSQL resource (`highfly-hospitality-staging-db` / `highfly_hospitality_staging`). This PR disables commit-triggered staging auto-deploy and removes `alembic upgrade head` from the build command so that a code commit/build does not implicitly deploy or migrate the staging database.

**This YAML is not evidence that Render has provisioned either resource.** The service may need to be created/updated by an authorized operator in the provider control plane. Provisioning, deployment, and migrations remain explicit operator actions. Before any migration, verify the target database, review migration impact, and obtain approval from the authorized operator.

Record the following in a completed copy of `frontdesk-acceptance-evidence-template.md`; do not store secrets, database URLs, tokens, guest documents, or real payment details:

- [ ] Provider control plane shows the staging web service and distinct staging PostgreSQL database exist.
- [ ] The service's database attachment is verified to reference the staging database—not DEV or production—and staging credentials/secrets are isolated.
- [ ] Operator records the deployed candidate SHA and database Alembic revision.
- [ ] Staging `/api/health` and `/api/ready` pass and readiness reports PostgreSQL mode.
- [ ] No production hostname, database, credential, or secret is configured in staging.
- [ ] Rollback owner and last known-good revision are documented.
- [ ] Tenant-negative and synthetic front-desk workflow tests are run against staging after the candidate is deployed through the approved process.
- [ ] Sanitized logs/screenshots or test reports are saved in the approved private evidence location.

## Manual front-desk acceptance and reconciliation

Run only after staging isolation is confirmed. Use fictional guests, synthetic identifiers, synthetic amounts, and test-only role accounts. Follow the acceptance template and record the exact candidate SHA, environment, tester, timestamps, expected/actual outcomes, and sanitized evidence reference.

- [ ] Create a reservation and assign an eligible clean room.
- [ ] Check in; verify reservation, stay, guest, property, and room linkage.
- [ ] Retry check-in, including a simulated retry after timeout; verify no duplicate stay, transaction, deposit, folio item, or successful audit event.
- [ ] Attempt cross-property reads/writes and invalid guest/room references; verify denial and no state mutation.
- [ ] Post a charge and payment; test idempotent payment replay and an unauthorized/invalid financial operation.
- [ ] Attempt checkout with an outstanding balance; verify atomic rejection and unchanged state.
- [ ] Settle the folio and checkout; retry checkout and verify there is only one business transition.
- [ ] Verify room status and housekeeping task creation, progression, completion, and resulting room availability.
- [ ] Reconcile folio charges, credits, paid amount, and balance against payment/refund/deposit records and ledger debit/credit totals. Record expected and actual values; all applicable differences must be zero.
- [ ] Confirm denied/retried actions do not create duplicate financial, operational, or successful audit writes.
- [ ] Tester and release owner sign off on the evidence record.

An unrun, unknown, or blocked item is not a pass. Do not infer route-family coverage from the selected regression tests alone.

## Isolated staging recovery drill

**Blocked until the authorized operator explicitly approves the staging backup source, recovery target, timing, and procedure.** No restore is authorized by this document. Never restore to production or use production guest/financial data for staging.

After approval, use an encrypted backup containing synthetic staging data only and restore it into a separate isolated recovery database. Record in the evidence template:

- [ ] Backup artifact reference, manifest, checksum, and integrity verification.
- [ ] Confirmed recovery target is separate from staging and production.
- [ ] Restore start/end timestamps and duration.
- [ ] Restored database/Alembic revision and schema checks.
- [ ] Pre/post synthetic reservation, stay, room, housekeeping, folio, payment, audit, and ledger counts/states.
- [ ] Pre/post folio totals and ledger debit/credit reconciliation.
- [ ] Missing records, warnings, defects, and sanitized evidence references.
- [ ] Operator and release owner review the results.

## Release decision

Remain **NO-GO** if CI is red/pending, a tenant-negative test mutates state, front-desk reconciliation is not exact, staging isolation is unverified, manual acceptance is incomplete, or isolated recovery evidence is absent. Health/readiness checks and green CI alone are insufficient.

No staging deployment, live migration, cloud acceptance run, or restore was performed while preparing this PR. Production remains out of scope and requires separate explicit approval.
