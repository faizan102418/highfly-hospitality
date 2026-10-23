# Front-desk release-readiness audit

**Scope:** cloud deployment candidate; first client = front desk; test data = synthetic only.  
**Status:** **NO-GO / external evidence incomplete** until required CI, staging, and recovery checks are recorded against the exact candidate SHA.

## Code and automated regression coverage in this PR

- First-admin bootstrap serializes PostgreSQL requests on the existing admin role row, then checks whether any user already exists while holding that transaction lock. Tenant slug/configuration conflicts are checked before creating the first user. Commit failures explicitly roll back.
- A PostgreSQL concurrency integration test creates an isolated temporary schema and races two bootstrap attempts. It expects exactly one administrator, one organization, one property, and one rejected request.
- Guest duplicate matching is filtered by the authorized property in SQL before the result limit. A busy foreign property can no longer consume the limited result set and hide an in-property duplicate.
- Cross-property regression tests cover foreign reservation check-in/checkout, stay reads, folio reads/payments, guest and room references during reservation creation, occupant references, reservation updates, and room-transfer destination references. Denials must not create new reservations or mutate foreign state.
- A synthetic PostgreSQL integration flow covers reservation, check-in retry denial, a posted charge, checkout rejection with an outstanding balance, an idempotent payment replay, exact folio total/paid/balance reconciliation, checkout retry denial, dirty-room handoff, and housekeeping task completion back to available.
- These tests are code-level evidence only. They do not establish that every registered legacy/canonical route family is tenant-isolated, nor do they replace manual acceptance on the deployed candidate.

## Cloud staging evidence

The checked-in render.staging.yaml defines a staging web service and a separate PostgreSQL database resource (highfly-hospitality-staging-db / highfly_hospitality_staging). The blueprint also declares commit-triggered auto-deploy and runs alembic upgrade head during build.

**Not verified by repository configuration alone:** whether the hosting provider has actually provisioned the service/database, whether the deployed service is connected to that exact database, which SHA/revision is live, or whether secrets/credentials are separated from DEV and production.

Required operator evidence (record without secrets or connection strings):

- [ ] Staging service and distinct PostgreSQL database are present in the provider control plane.
- [ ] Operator confirms the intended staging database attachment and isolated credentials.
- [ ] Deployed candidate SHA and Alembic revision are recorded.
- [ ] /api/health and /api/ready succeed in staging and report PostgreSQL mode.
- [ ] The new tenant-negative and synthetic workflow tests pass against staging with synthetic data only.
- [ ] Manual front-desk acceptance is recorded using frontdesk-acceptance-evidence-template.md.

No deployment or migration was performed by this audit.

## Recovery evidence

CI's backup/restore round trip uses a disposable CI database; it is not a cloud staging restore drill.

A cloud drill remains **BLOCKED** until the operator confirms the staging environment and approves the exact isolated recovery target and procedure. When approved, use a synthetic staging backup only and restore into a separate isolated recovery database—never production. Record artifact/manifest/checksum, restored revision, synthetic row counts, room/reservation states, audit evidence, folio totals, ledger debit/credit totals, and duration in the acceptance evidence template.

No staging restore or production backup/restore was performed by this audit.

## Release gate

Remain **NO-GO** if CI is red or pending, any tenant-negative check mutates data, the synthetic financial reconciliation is not exact, staging isolation is unverified, or isolated recovery evidence is absent. Passing health/readiness checks alone is not a release decision.
