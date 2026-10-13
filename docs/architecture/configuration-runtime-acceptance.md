# Configuration runtime acceptance

## Findings

The configuration API resolves organization defaults, property overrides, and platform defaults. The reviewed operational code does not yet consume every resolved value consistently:

- Front-desk flows do not consistently consume effective check-in/check-out defaults.
- Billing and night audit each define a fixed 10% food service-charge rate instead of using the configured service-charge setting.
- Deposit amounts are driven by stay/reservation values; tax, service-charge, and approval-threshold settings are not shared inputs.
- Billing helpers still use fixed two-decimal rounding although a billing-rounding setting exists.
- Property branding is available through a scoped API; document renderers need an end-to-end check that they use the selected property's branding.

Financial settings are not activated in this change because the same rule must govern postings, reversals, invoices, and reconciliation. Changing only a display calculation could make a folio disagree with the authoritative ledger.

## Automated evidence

The API tests cover two properties in one organization and verify that a property override and branding change do not leak to the other property. PostgreSQL backup/restore CI now seeds an organization default, property overrides, and branding, then checks those values in the disposable recovery database.

## Separate Windows development acceptance

Run with a separate development installation and disposable database. Do not target the production database.

1. Record the app commit, database engine, and migration revision; verify the configured database is the development instance.
2. Create two test properties in one organization and a test admin with access to both.
3. Set organization language and check-in-time defaults; confirm both properties inherit them.
4. Override language and currency on Property A; confirm Property B retains the organization language and platform currency.
5. Change Property A branding; confirm Property B branding is unchanged.
6. Use front desk on both properties and compare arrivals, departures, business date, availability, and check-in/out defaults with effective settings.
7. Create test charges, payments, deposits, a deposit transfer/replay, and a night audit. Compare folio totals, ledger entries, and night-audit totals; any mismatch blocks rollout.
8. Back up the development database and restore into a different disposable database. Verify organization defaults, property overrides, and branding. Never restore over the source database.
9. Restart while offline and test sign-in, front desk, billing, housekeeping, and reports. Record screens that require network access.
10. Remove disposable databases and test artifacts after recording evidence.

## Status

- Automated property isolation: added to CI.
- Automated configuration backup/restore preservation: added to CI.
- Windows offline workflow: not executed by CI; run and record it on the separate development laptop before rollout.
- Effective-setting consumption in financial workflows: incomplete; the findings above are explicit follow-up work.
