# Cloud first-client release gate — front desk acceptance

This checklist complements automated CI for the first-client front-desk scope. A checked box means the step was performed in an isolated demo/test property and evidence recorded; CI success alone does not complete a manual item. Use the [front-desk acceptance evidence template](frontdesk-acceptance-evidence-template.md) to capture the candidate SHA, tester/environment, per-gate results, reconciliation totals, restore evidence, and release decision.

## Safety and test setup

- [ ] Confirm the target is a dedicated demo/test deployment and database, not production.
- [ ] Use fictional guest names, contact details, room numbers, and payment references only.
- [ ] Record the release commit SHA, environment, tester, date/time, and browser/OS.
- [ ] Confirm the cloud candidate uses production mode, PostgreSQL, and strong unique secrets supplied through the hosting secret manager. Never paste secret values into evidence.
- [ ] Confirm `/api/ready` returns HTTP 200 and reports PostgreSQL readiness. This proves connectivity only, not workflow correctness.
- [ ] Create two test properties and users: one authorized for Property A only, and one for Property B. Use disposable data.

## A. Login, authorization, and property scope

- [ ] Sign in with the Property A front-desk user; confirm the front-desk workspace loads.
- [ ] Attempt to access a Property B guest, reservation, room, stay, or folio by direct URL/API identifier. Expect denial/not-found behavior and no data disclosure.
- [ ] Attempt a write against a Property B record. Expect denial and verify no record, ledger, or audit mutation was created.
- [ ] Confirm a user without the required role cannot perform restricted financial or administration actions.
- [ ] Confirm successful operational audit entries identify the correct property and actor.

## B. Reservation and room assignment

- [ ] Create a fictional guest and reservation with valid arrival/departure dates.
- [ ] Confirm the selected room is available and the reservation appears in front-desk/reservation views.
- [ ] Attempt a second overlapping reservation for the same room and dates. Expect a conflict; verify the first booking and room state remain unchanged.
- [ ] Try invalid dates (departure on/before arrival) and a dirty/out-of-order room. Expect validation and no partial writes.
- [ ] Refresh and reopen the reservation; confirm guest, dates, room, rate, and status persist.

## C. Check-in, stay, and room transfer

- [ ] Check in the reserved guest. Verify reservation/stay status, actual check-in timestamp, and room occupancy agree.
- [ ] Repeat check-in (or retry after a simulated timeout). Confirm it does not create duplicate stays, charges, or audit events.
- [ ] Transfer the checked-in guest to another available room. Confirm stay and reservation room links change together and the old room is released according to the documented housekeeping workflow.
- [ ] Attempt transfer to occupied, reserved, dirty, out-of-order, or cross-property room. Expect rejection and no partial writes.
- [ ] Confirm the guest and all occupants belong to the same property; cross-property occupant references must be rejected.

## D. Charges, deposits, payments, and folio

Use small known test amounts and record expected totals before each operation.

- [ ] Receive a deposit. Verify deposit record, audit event, and balanced ledger posting agree on amount, method, property, reservation, and stay.
- [ ] Repeat the same request with the same idempotency key/reference where supported. Verify no duplicate deposit or ledger posting.
- [ ] Attempt an invalid/over-balance refund or deposit application. Expect rejection and verify no partial deposit, payment, ledger, or audit writes.
- [ ] Apply a valid deposit to the folio. Verify exactly one folio payment is created, deposit balance decreases once, and ledger remains balanced.
- [ ] Add an authorized charge and record a payment. Reconcile folio line items, payments, deposit application, and displayed balance using decimal currency values.
- [ ] Verify a failed/declined/invalid payment leaves no partial financial records.
- [ ] Verify posted billing entries are not silently edited; corrections use the supported reversal/correction flow.

## E. Checkout and housekeeping

- [ ] Attempt checkout with an outstanding balance. Expect rejection; verify reservation/stay remain checked in and folio remains open with no partial checkout writes.
- [ ] Settle the folio to exactly zero and check out. Verify folio closes, reservation/stay transitions complete, actual checkout timestamp is recorded, and the correct room enters the configured housekeeping state.
- [ ] Repeat checkout. Expect a safe conflict/no-op; verify no duplicate charges, payments, or audit transitions.
- [ ] Confirm unrelated rooms and reservations retain their prior status.

## F. Recovery and release evidence

- [ ] Run the supported backup procedure against the disposable test database and verify artifact, manifest, and checksum.
- [ ] Restore only into a separate isolated recovery database; verify test guest, reservation, room state, and financial balances match the pre-backup record.
- [ ] Record pass/fail for every item, sanitized screenshots/log excerpts, expected vs actual totals, and linked defect issues.
- [ ] Confirm required CI checks passed on the exact candidate commit and review skipped/neutral checks.
- [ ] Confirm rollback owner, backup retention, incident contact, and release decision are documented.

## Release decision

**GO** only when all applicable items pass, financial totals reconcile, cross-property negative tests show no writes, recovery evidence is recorded, and CI is green on the candidate SHA.

**NO-GO** if authorization boundaries, duplicate/retry behavior, room-state transitions, ledger balance, checkout rollback, backup/restore, or cloud configuration fail or remain untested. Record the failure as a defect; do not use production guest or financial data to reproduce it.

This checklist does not authorize production deployment, production migrations, or a live production backup/restore. Those remain separately approved operator activities.
