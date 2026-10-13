# Property ownership design decisions

**Status:** Proposal for review only. This document changes no application behavior, schema, migration, or deployed database.

**Scope:** Resolve product/schema decisions needed before implementation work following the ownership inventories in `property-ownership-schema-map.md` and `complete-schema-ownership-audit.md`.

## 1. Recommended decisions for approval

These are proposals, not implemented behavior.

| Topic | Recommended v1 decision | Reason / guardrail |
|---|---|---|
| Tenant root | Organization owns one or more properties; every operational record belongs to exactly one property directly or through a verified parent chain. | Keeps access and reporting boundaries explicit. |
| Global user identity | Keep authentication identity global; grant no property access solely because a user can sign in. | Membership and authorization are separate concerns. |
| Standard roles | Keep built-in roles platform-defined for v1. Do not make the existing global `roles` table implicitly tenant-customizable. | Customer-defined roles require an explicit scope, permission model, and migration/API design. |
| Custom roles | Defer until organization/property scope, permission granularity, role assignment, and backward compatibility are designed. | Avoids a partial RBAC model that can widen access unexpectedly. |
| Guest records | Keep `guests` property-owned in v1. | Cross-property guest identity is a distinct Guest 360 feature; do not share guests by relaxing foreign-key checks. |
| Supplier records | Keep `suppliers` property-owned in v1. | Organization-wide supplier sharing can be introduced later with an explicit organization-owned supplier model and links. |
| Configuration precedence | Property override → organization default → documented platform default. | Property-specific operational behavior remains authoritative; null removes an override at its own scope. |
| Branding | Property-owned only; never inherit another property's branding. | Prevents cross-property invoices, receipts, and guest documents from using the wrong identity. |
| Secrets | No credentials, signing keys, or connection secrets in settings/branding tables. | Keep secrets in environment/secret management. |
| Posted financial history | Preserve amounts, taxes, service charge, currency, and policy snapshots used at posting time. Correct posted records through auditable reversal/correction workflows. | Current configuration changes must not rewrite historical accounting. |
| Child-table tenant key | Prefer deriving ownership through the authoritative parent; add a direct `property_id` only when there is a documented query/integrity reason and consistency is enforceable. | Avoids redundant ownership columns that can disagree. |
| Tenant enforcement | Service authorization on every read/write plus database constraints for critical same-property relationships where supported. | A valid foreign key alone does not prove both rows belong to the same property. |
| Database support | Treat SQLite and PostgreSQL as separate test targets; document any invariant that is only enforced on PostgreSQL and provide a portable safeguard where required. | Revision `0023` has PostgreSQL-specific trigger behavior. |

## 2. Blocking schema reconciliation: folio-window names

The source audit found a material naming discrepancy:

- ORM metadata and legacy SQL use `folio_windows`.
- Alembic revision `0005_stay_folio_windows` explicitly creates/adopts `stay_folio_windows`.
- Revision comments indicate metadata bootstrap may already have created a target table, but that does not establish that all installation paths converge on the same schema.

**Decision required:** Do not rename, drop, merge, or create a compatibility view for either table until we can demonstrate the intended schema on each supported installation path.

Required evidence before proposing DDL:

1. Inspect the exact model declaration, revision `0005`, later migrations, legacy SQL, and runtime bootstrap behavior.
2. Run fresh Alembic-only and supported metadata-bootstrap installs against disposable SQLite and PostgreSQL databases.
3. Compare actual tables, columns, constraints, indexes, and references.
4. If both names can exist, define a non-destructive data reconciliation plan and tests before any migration is proposed.
5. Confirm the actual revision and schema of any target environment separately; source code alone does not establish deployed state.

## 3. Relationship integrity requirements

The following relationships need same-property validation, in both service code and database constraints where feasible:

- Reservation ↔ room assignments; stay ↔ reservation, room, and guest; room move ↔ stay and both rooms.
- Folio ↔ reservation; folio item ↔ folio and optional stay; payment/refund ↔ original payment and folio; deposit ↔ stay and optional folio.
- Invoice ↔ folio; financial transaction ↔ any linked folio/reservation; ledger entry ↔ transaction and optional folio/stay.
- Restaurant order ↔ folio/reservation; order item ↔ menu item and optional folio item.
- Purchase order ↔ supplier; purchase order line ↔ stock item; goods receipt ↔ order/supplier; goods receipt line ↔ receipt, PO line, and stock item.
- Housekeeping/maintenance task ↔ room; actor/assignee must have access to that room's property.

For every path, tests should prove that a user cannot read, create, update, delete, post, refund, route, receive, or export data by substituting another property's identifier.

## 4. Tenant-scoped uniqueness review

Before changing any unique constraint, inspect existing definitions and test duplicate data in disposable schemas. Explicitly decide scope for:

- Room number and room-type name.
- Supplier code, stock SKU/name, and menu-item name.
- Purchase-order and goods-receipt numbers.
- Expense/invoice numbering and financial idempotency keys.
- Organization slug and organization-local property code/slug.
- Global user identity fields.

Do not drop a global constraint merely because property-scoped uniqueness seems more convenient. Define the intended business scope, migration collision handling, and compatibility behavior first.

## 5. Implementation gate

No ownership migration or application behavior change should begin until the following are reviewed:

- [ ] Approve or revise the proposed decisions in section 1.
- [ ] Resolve the `folio_windows` / `stay_folio_windows` compatibility question with repeatable tests.
- [ ] Produce a source-backed table/relationship inventory covering ORM metadata, Core declarations, Alembic, legacy SQL, and runtime bootstrap.
- [ ] Record current foreign keys, unique constraints, indexes, and ownership paths for each table.
- [ ] Identify exact endpoint/service/query paths requiring authorization changes.
- [ ] Define safe handling for populated legacy data; never infer property ownership from hotel names, IDs, or assumptions.
- [ ] Define SQLite and PostgreSQL test coverage, including fresh install and supported upgrade paths.
- [ ] Review the proposed implementation diff before any migration is applied to a non-disposable database.

After approval, implement in separate, reviewable pull requests: (1) remaining source inventory and schema parity tests, (2) tenant-isolation service/test fixes, and only then (3) any justified migration. Never test destructive migration behavior against production.

## 6. Explicit non-goals

This proposal does not create migration `0024`, change application code, rename/drop tables, change RBAC, share guest/supplier records, backfill tenant ownership, run migrations, inspect or mutate a deployed database, or alter Render configuration.
