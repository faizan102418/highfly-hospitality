# Front-desk acceptance evidence record

Use one copy of this record per release candidate. Store evidence in the approved private project/release location; link to it rather than pasting guest data, credentials, database URLs, payment references, or other secrets into GitHub.

## Run metadata

| Field | Value |
|---|---|
| Candidate commit SHA | |
| PR / release reference | |
| Environment name and URL (no credentials) | |
| Database type / readiness result | |
| Staging service/resource identifiers (non-secret names only) | |
| Operator-confirmed database resource and isolation | |
| Deployed Alembic revision | |
| Tester / authorized operator | |
| Start / end time with timezone | |
| Browser and OS | |
| Test properties and role accounts (synthetic IDs only) | |
| Checklist revision | |

## Staging safety gate

| Check | Result (Pass / Fail / Blocked) | Sanitized evidence reference / notes |
|---|---|---|
| Provider control plane confirms staging service exists | | |
| Separate staging PostgreSQL resource exists | | |
| Service is attached to the intended staging database, not DEV/production | | |
| Credentials and secrets are isolated; no secret values recorded here | | |
| Candidate SHA and deployed database revision are recorded | | |
| HTTPS and health/readiness checks pass; readiness reports PostgreSQL mode | | |
| Synthetic data only; no production guest/financial data | | |
| Rollback owner, trigger, and last known-good revision recorded | | |
| Authorized operator approved deployment/migration where applicable | | |

## Result summary

| Area | Pass / Fail / Blocked / Not applicable | Evidence reference | Defect issue / notes |
|---|---|---|---|
| Environment is isolated; synthetic data only | | | |
| Login, roles, and cross-property read/write denial | | | |
| Reservation validation and overlap conflict | | | |
| Check-in, repeated check-in, room transfer | | | |
| Deposits, ledger, folio, payment and retry behavior | | | |
| Checkout, outstanding-balance rejection, housekeeping | | | |
| Backup artifact, manifest, checksum, isolated restore | | | |
| CI and workflow checks on exact candidate SHA | | | |
| Rollback owner, retention, incident contact | | | |

## Financial reconciliation

Use the smallest practical synthetic amounts. Record currency and decimal amounts explicitly; never include real payment details.

| Scenario / synthetic reference | Expected folio balance | Actual folio balance | Expected ledger debit/credit | Actual ledger debit/credit | Duplicate writes? | Result / evidence |
|---|---:|---:|---|---|---|---|
| Deposit received | | | | | | |
| Deposit applied to folio | | | | | | |
| Charge and payment | | | | | | |
| Invalid/over-balance operation | No mutation | | No mutation | | | |
| Checkout with outstanding balance | Rejected; no mutation | | No mutation | | | |
| Successful checkout and retry | One transition only | | No duplicate posting | | | |

## Recovery verification

Do not begin this section until the authorized operator has approved the synthetic staging backup source, isolated recovery target, timing, and procedure.

- Operator approval reference and timestamp:
- Backup target was synthetic staging data only:
- Artifact reference (not a public URL if access-controlled):
- Manifest and checksum verified:
- Restore target is a separate isolated database, not staging or production:
- Restore start/end timestamps and duration:
- Restored schema/Alembic revision:
- Pre/post synthetic reservation, stay, room, housekeeping, folio, payment, audit, and ledger counts/states:
- Pre/post folio totals and ledger debit/credit totals:
- Any missing data or warnings:
- Evidence reference:
- Operator review and outcome:

## Defects and exceptions

For each failed or blocked item, record the expected behavior, actual behavior, synthetic record identifiers, sanitized evidence reference, severity, and linked issue. Do not mark a blocked/unrun check as passed. Do not waive security, tenant-isolation, financial-integrity, retry/idempotency, checkout-rollback, or recovery gates.

## Release decision

- [ ] **GO** — every applicable critical gate passed, financial reconciliation is exact, restore evidence is recorded, and required checks are green on the candidate SHA.
- [ ] **NO-GO** — any critical gate failed, is blocked, or remains untested.
- [ ] **Not decided** — evidence is incomplete.

Decision owner:
Decision timestamp:
Outstanding conditions / approved exceptions:
Rollback owner and trigger:
Incident contact:

**Safety boundary:** this record is not authorization to deploy, run migrations, access production guest/financial data, or perform a live production backup/restore. Those actions require separate explicit approval and the approved operator procedure.
