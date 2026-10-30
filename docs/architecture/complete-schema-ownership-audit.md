# Complete schema and tenant-ownership audit

**Status:** Source inventory and design review only. No application behavior, schema migration, deployed database, or production data was changed.
**Baseline:** `main` commit `163a4b2cc82d102ea8da635b5fd39e75039187ea` (PR #44 merged).
**Purpose:** Reconcile migration/bootstrap/runtime schema sources with the initial `property-ownership-schema-map.md` before proposing schema changes.

## Executive summary

The existing ownership map is a useful starting point, but it is **not yet a complete source-of-truth inventory**. This pass found concrete naming and coverage gaps that must be resolved before any ownership migration is designed:

1. The map lists `purchase_order_items`, `purchase_receipts`, and `purchase_receipt_items`, while the current purchasing Core tables are named `purchase_order_lines`, `goods_receipts`, and `goods_receipt_lines`.
2. The map does not include confirmed schema objects `payment_refunds`, `folio_item_windows`, `folio_item_routing`, and `invoices`.
3. The folio-window names are now source-resolved as two distinct tables: `folio_windows` is the legacy/group-level payer-window model without `stay_id`, while `stay_folio_windows` is the stay-specific model with `stay_id -> stays.id`. Revision `0005_stay_folio_windows` creates/adopts only the latter name. This resolves the naming question, but fresh-install and supported-upgrade schema parity still require execution tests.
4. The map lists `maintenance_requests`, but the inspected current Core table is `maintenance_blocks`; no `maintenance_requests` creation was confirmed in the reviewed sources.
5. The schema is not defined solely by explicit `op.create_table` calls. Revisions `0001`, `0003`, `0004`, and `0013` use SQLAlchemy metadata `create_all`; runtime startup in `apps/api/app/db.py` also contains compatibility ALTER statements. A grep of explicit migration DDL alone is therefore insufficient.

These are documentation and verification findings, **not a declaration that a live or deployed database has these exact objects**. No deployed database was inspected.

## Schema sources in scope

### Alembic revision chain

The repository's `apps/api/alembic/versions` directory contains the sequential revisions:

- `0001_initial_hms` — imports `app.models` and `app.pms_core`, then creates registered SQLAlchemy metadata.
- `0002_backfill_phase_a`
- `0003_financial_ledger` — imports core models and ledger metadata, then calls `create_all`.
- `0004_phase_b_financial_ops` — imports financial models and calls `create_all`.
- `0005_stay_folio_windows` — creates/adopts `stay_folio_windows`.
- `0006_phase_a_folio_item_routing` — creates `folio_item_routing`.
- `0007_financial_idempotency`
- `0008_seed_business_date`
- `0009_ledger_integrity`
- `0010_ledger_balance_integrity`
- `0011_reservation_lifecycle_integrity`
- `0012_night_audit_closure_lock`
- `0013_restaurant_pos_integrity` — imports core metadata and calls `create_all`, plus PostgreSQL guards.
- `0014_inventory_control` — adds `stock_operations` and related checks/indexes.
- `0015_purchasing_integrity` — adds purchasing and goods-receipt tables.
- `0016_housekeeping_integrity` — adds housekeeping and maintenance tables.
- `0017_stacked_discounts` — documents a semantic change; no schema DDL.
- `0018_hotel_expenses` — adds/backfills expense fields and related integrity.
- `0019_business_date_closure` — adds/updates business-date closure state and guard logic.
- `0020_multi_tenant_foundation` — organization/property/access/settings foundation.
- `0021_property_ownership` — adds `property_id` to a declared list of existing tables and refuses to infer ownership for populated legacy roots.
- `0022_property_config` — organization settings and property branding.
- `0023_property_date_guards` — PostgreSQL property-aware business-date guard functions/triggers; non-PostgreSQL databases return without creating these triggers.

The exact revision graph and schema behavior still need to be exercised against fresh SQLite, fresh PostgreSQL, and an upgrade from each supported legacy baseline. Source inspection is not a substitute for migration execution tests.

### Other schema sources

- SQLAlchemy ORM metadata: `apps/api/app/models.py`, `pms_core.py`, `tenancy.py`, and `financial_models.py`.
- SQLAlchemy Core table declarations: `apps/api/app/inventory.py`, `purchasing.py`, and `housekeeping_control.py`.
- Runtime compatibility schema edits: `apps/api/app/db.py` (including additions for reservation timestamps, `folio_items.stay_id`, and business-date state).
- Legacy SQL: `database/migrations/005_pms_core_2.sql` creates `booking_groups`, `group_reservations`, `stays`, and `folio_windows`; `database/migrations/006_financial_ledger_2.sql` adds `folio_items.stay_id`.
- PostgreSQL-only function and trigger DDL embedded in revisions `0009`–`0013` and `0023` must be inventoried as database behavior, even though those objects are not tables.

## Confirmed source-level table inventory and proposed ownership

This is the reconciled inventory of table names found in the inspected model/Core declarations and migration sources. Ownership below is a design proposal; it is not proof that all current endpoints enforce the proposal.

### Identity, tenancy, configuration, audit

| Table | Proposed ownership | Required invariant / decision |
|---|---|---|
| `organizations` | Organization root | Globally unique organization slug; authorized organization administration. |
| `properties` | Property root | Organization is authoritative; property code/slug unique within organization. |
| `users` | Global identity | Authentication identity does not grant property access. Review global username/email uniqueness and lifecycle. |
| `roles` | Shared/platform roles today | Decide whether custom roles will be organization-scoped; do not overload global roles without an explicit model. |
| `property_user_access` | Membership/access relation | Membership, role, scope, and organization/property consistency must be explicit and revocable. |
| `property_settings` | Property configuration | Unique by property and key; validate typed values. |
| `organization_settings` | Organization configuration | Unique by organization and key; authorization must require organization-level rights. |
| `property_branding` | Property configuration | One row per property; no secrets in branding/config values. |
| `audit_logs` | Property-scoped audit | Actor and target must be authorized for the same property; avoid secrets and excessive sensitive payloads. |

### Rooms, guests, reservations, stays

| Table | Proposed ownership | Required invariant |
|---|---|---|
| `room_types` | Property root | Name uniqueness should be property-scoped unless a deliberately shared catalogue is designed. |
| `rooms` | Property root | Room number unique within property; room type belongs to same property. |
| `guests` | Property root in current model | Guest references must remain same-property. Cross-property Guest 360 needs a deliberate organization-level identity/link design. |
| `reservations` | Property root | Guest, dates, status and associated rooms must be consistent with property and lifecycle rules. |
| `reservation_rooms` | Child/join of reservation and room | Both parent records must resolve to the same property. |
| `booking_groups` | Property root | Primary guest and all group reservations must resolve to the same property. |
| `group_reservations` | Child/join of group and reservation | Both sides must be in the same property. |
| `stays` | Child of reservation | Reservation, room and optional guest must agree on property; derive authority from reservation. |
| `reservation_splits` | Child of source/new reservations | Both reservations must be same-property; retain audit history. |
| `room_moves` | Child of stay | Stay, source room and destination room must be same-property. |
| `stay_occupants` | Child of stay and guest | Stay and guest must be same-property under current guest model. |
| `stay_rate_segments` | Child of stay | Validate dates/rates; preserve posted historical values. |

### Folios, payments and accounting

| Table | Proposed ownership | Required invariant |
|---|---|---|
| `folios` | Child of reservation | Reservation is authoritative; all linked financial objects must resolve to the same property. |
| `folio_items` | Child of folio, optional stay | Optional stay must agree with folio/reservation and property. |
| `folio_windows` | Legacy/group-level payer window, child of folio | Distinct legacy model; it has no `stay_id` column. Do not reinterpret it as the stay-specific window table. |
| `stay_folio_windows` | Stay-specific payer window, child of folio and stay | Declared by `StayFolioWindow`; `stay_id` references `stays.id`. Revision `0005_stay_folio_windows` creates/adopts this exact table name. |
| `folio_item_windows` | Child/link of folio item and folio window | Both relationship paths must resolve to the same folio/property. |
| `folio_item_routing` | Child/link of folio item and window | Routing target must belong to the same folio/property; idempotency and uniqueness semantics need tests. |
| `payments` | Child of folio | Payment authorization and folio ownership must agree; protect posting/idempotency. |
| `payment_refunds` | Child of payment/folio | Refund must reference the original payment and matching folio/property; enforce refundable balance and authorization. |
| `deposit_transactions` | Child of stay, optional folio | Stay, folio, reservation and actor must agree on property. |
| `financial_transactions` | Property-owned financial root | Direct property is authoritative; referenced records must match; reversal/idempotency rules must hold. |
| `ledger_entries` | Child of financial transaction | Any optional folio/stay links must resolve to same property; posted ledger entries should be append-only/reversed, not silently rewritten. |
| `invoices` | Child of folio | Invoice and folio must share property; confirm number uniqueness and lifecycle. |
| `invoice_sequences` | Property-scoped state | Exactly one active sequence per property; never global/shared across tenants. |
| `expenses` | Property root | Expense number uniqueness should be property-scoped; creator and any linked financial transaction must be consistent. |
| `business_date_state` | Property-scoped state | One state per property; every posting guard resolves state by property, never a global singleton. |

### Restaurant, inventory and purchasing

| Table | Proposed ownership | Required invariant |
|---|---|---|
| `menu_items` | Property root | Name/SKU uniqueness should be property-scoped. |
| `restaurant_orders` | Property root | Folio, reservation and creator must match order property; status transitions and business date must be guarded. |
| `restaurant_order_items` | Child of restaurant order | Menu item and optional folio item must match the order property; preserve void/reversal history. |
| `stock_items` | Property root | SKU/name uniqueness property-scoped; validate units and nonnegative stock policy. |
| `stock_movements` | Child of stock item | Property derives from stock item; business date and actor must be valid for that property. |
| `stock_operations` | Child of stock item | Operation and idempotency identifiers need deliberate scope; business date/property must resolve through stock item. |
| `suppliers` | Property root in current design | Supplier code uniqueness should be property-scoped if hotels can reuse codes; organization-wide supplier sharing is a separate feature. |
| `purchase_orders` | Property root | Supplier, creator, lines and business date must all match property. |
| `purchase_order_lines` | Child of purchase order | Stock item and order must share property. This is the actual current table name found in Core declarations. |
| `goods_receipts` | Child of purchase order | Purchase order, supplier, property, business date and idempotency key must be consistent. |
| `goods_receipt_lines` | Child of receipt and PO line | Receipt and PO-line paths must resolve to the same PO/property; stock item must agree. |

### Housekeeping and maintenance

| Table | Proposed ownership | Required invariant |
|---|---|---|
| `housekeeping_tasks` | Child of room | Room determines property; assigned/completing/creating users must be authorized. |
| `maintenance_blocks` | Child of room | Room determines property; reporting/resolving users must be authorized; business date must match property state. |

## Naming mismatches and coverage corrections required in the ownership map

| Existing map entry | Source-level finding | Action before migration design |
|---|---|---|
| `purchase_order_items` | Current Core declaration is `purchase_order_lines`. | Correct documentation and inspect all route/service references. |
| `purchase_receipts` | Current migration/Core name is `goods_receipts`. | Correct documentation; review receipt idempotency and property derivation. |
| `purchase_receipt_items` | Current migration/Core name is `goods_receipt_lines`. | Correct documentation; verify both parent paths. |
| `maintenance_requests` | Current inspected table is `maintenance_blocks`; no matching create was confirmed. | Remove or mark as future-only unless a separate supported source is found. |
| Missing `payment_refunds` | Declared in `financial_models.py`. | Add ownership, same-property and refundable-balance rules. |
| Missing `folio_item_windows` | Declared in `financial_models.py`. | Add dual-parent consistency rules. |
| Missing `folio_item_routing` | Created by revision `0006`. | Add ownership and window/folio integrity rules. |
| Missing `invoices` | Declared in `financial_models.py`. | Add folio ownership, invoice numbering, and immutability/lifecycle rules. |
| `folio_windows` vs `stay_folio_windows` | Two distinct source-level models with different parent semantics. | Keep both names and relationships distinct; verify fresh-install and supported-upgrade schema parity before any DDL. |

## Cross-cutting risks to resolve

1. **Tenant isolation is a relationship property, not just a column.** A `property_id` column does not stop a child from referencing a foreign parent in another property. Composite foreign keys or equivalent database constraints should be considered for high-risk paths, backed by service authorization.
2. **Tenant-scoped uniqueness.** Review globally unique room numbers, room-type names, supplier codes, PO numbers, GRN numbers, stock identifiers, menu names and expense numbers. Global identity and organization/property slugs are different and may legitimately remain global or organization-scoped.
3. **IDOR and secondary access paths.** Audit direct ID fetches, mutations, joins, reports, exports, background tasks, scheduled jobs and file/document access. A session or user ID alone is not authorization.
4. **Financial integrity.** Preserve immutable posted history; use reversals/corrections, verify refund caps, idempotency, same-property links, and property-scoped business dates.
5. **Configuration ownership.** Property override → organization default → documented platform fallback. Validate types and allowed keys; keep credentials/secrets out of configuration tables.
6. **SQLite/PostgreSQL parity.** Revision `0023` skips trigger creation outside PostgreSQL. Every critical invariant enforced by a PostgreSQL trigger needs a portable service/database equivalent and tests for SQLite, or an explicit supported-database policy.
7. **Fresh install vs upgrade.** Metadata `create_all`, Alembic revisions, legacy SQL scripts, and runtime `db.py` alterations overlap. Test each supported path and assert schema equivalence; avoid relying on import-time metadata to make Alembic-only installs work accidentally.
8. **Migration safety.** Revision `0021` correctly refuses to guess ownership of populated operational roots. Any eventual backfill must be explicit, reviewed, reversible where feasible, and fail closed on ambiguous rows.
9. **Authorization model decisions.** Decide whether roles are global or customer-defined and whether guest profiles remain property-local. Do not implicitly share records across properties.

## Review gate and next steps

- [ ] Compare the above table inventory with live model metadata and every migration source in CI; generate a machine-readable table inventory in tests if feasible.
- [ ] Exercise fresh SQLite, fresh PostgreSQL, and supported upgrade paths through revision `0023`; compare tables, columns, indexes, unique constraints, foreign keys and triggers.
- [ ] Inspect every property-bearing root and each child foreign-key chain for cross-property writes and reads.
- [ ] Fix remaining purchasing/maintenance documentation naming mismatches; keep the distinct folio-window contract covered by tests and verify fresh-install/upgrade parity before any schema change.
- [ ] Add cross-tenant negative tests for read/list/report/export/create/update/delete, plus financial posting/refund/purchasing/housekeeping flows.
- [ ] Decide roles and guest-sharing policies.
- [ ] Only after review, propose implementation migrations as a separate pull request with safe failure behavior and no guessed legacy ownership.

## UI/UX sequencing

The schema audit should not block all design work. In parallel with review of this artifact, the next product-facing phase should establish a coherent UI shell and design system, then implement the dashboard, room status/availability, and front-desk reservation/check-in/check-out workflow. The remaining modules (folios/payments, POS, inventory/purchasing, housekeeping/maintenance, reports and administration) should follow the same shared patterns. UI work should use real API contracts and tenant context, not hard-coded demo data, and must not bypass server-side authorization.

## Explicit non-goals

This artifact does not create revision `0024`, change runtime application behavior, rename/drop any table, assign legacy rows to a property, inspect a deployed database, provision cloud infrastructure, or touch production data.
