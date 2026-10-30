# Property ownership and tenant-boundary schema map

**Status:** Design review only. No schema migration or application behavior is changed by this document.

**Reviewed baseline:** `main` at the time this map was prepared, including Alembic revisions `0020_multi_tenant_foundation`, `0021_property_ownership`, `0022_property_config`, and `0023_property_date_guards`, plus the SQLAlchemy models in `apps/api/app/models.py`, `pms_core.py`, and `tenancy.py`.

## 1. Purpose and boundary

HighFly Hospitality is a cloud-first, multi-tenant SaaS PMS. La Serene is a reference property, not a special case in application logic. Every request and every data mutation must be scoped to an authorized property and its owning organization.

This inventory is a design aid, not proof that every existing query, foreign key, or unique constraint is tenant-safe. The folio-window naming contract is source-resolved, but deployed schema parity is not proven. Before any ownership migration is proposed, inspect all migration-created tables, bootstrap/legacy schema paths, raw SQL, report queries, and write paths against this map.

## 2. Ownership classes

- **Platform/shared reference:** non-customer-specific definitions managed by the platform. Do not store hotel operational records here.
- **Organization-owned:** belongs to one customer organization and may be shared among its properties when the domain explicitly allows it.
- **Property-owned root:** has an authoritative `property_id` and belongs to one property.
- **Property child:** has no independent tenant identity; its property is derived through its authoritative parent. Validate all cross-table references stay within that same property.
- **Configuration child:** belongs to an organization or property through its configuration owner and follows explicit override precedence.
- **Identity/membership:** global identity may authenticate once, but organization/property access must be explicit and revocable.

## 3. Table inventory

The current model contains more than the core front-desk tables. The following is the proposed ownership classification to review before further schema work.

### Tenant platform and configuration

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `organizations` | Organization root | One customer account; unique slug is global. |
| `properties` | Property root, child of organization | `organization_id` is authoritative. |
| `property_user_access` | Membership/access relation | Must only grant access to properties within the intended organization; validate role/permission semantics. |
| `roles` | Shared role definitions or organization-scoped roles (decision needed) | Current globally unique role names may be too restrictive for customer-defined roles. Do not decide by migration accident. |
| `users` | Identity root | Login identity may be global; property access is not implied by having a user account. Review username/email uniqueness and membership lifecycle. |
| `property_settings` | Property configuration child | Unique per property + key; validate setting key/value by schema. |
| `organization_settings` | Organization configuration child | Unique per organization + key; platform fallback belongs in application policy, not customer rows. |
| `property_branding` | Property configuration child | One row per property; contains presentation/contact settings, not secrets. |
| `audit_logs` | Property-owned audit record | Property and actor must be authorized and consistent. Avoid sensitive payloads. |

### Rooms, guests and reservations

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `room_types` | Property-owned root | Name uniqueness should normally be property-scoped, not global. |
| `rooms` | Property-owned root | Room number uniqueness should normally be property-scoped. `room_type_id` must reference a room type in the same property. |
| `guests` | Property-owned for current schema; future CRM sharing decision | Current model includes `property_id`. If guest profiles are shared across properties, share only within an organization using an explicit organization-scoped identity/link model. |
| `reservations` | Property-owned root | `guest_id` must belong to the same property under the current model. Dates/statuses require domain validation. |
| `reservation_rooms` | Property child / join | Both reservation and room must belong to the same property. |
| `booking_groups` | Property-owned root | Group reservations must not cross property boundaries unless a future multi-property group-booking model explicitly supports it. |
| `group_reservations` | Property child / join | Both sides must belong to the same property/group. |
| `stays` | Property child of reservation | Room, reservation and guest references must agree on property. Derive property from the reservation rather than trusting client-supplied IDs. |
| `reservation_splits` | Property child of source/new reservations | Both reservations must belong to the same property; retain audit/history. |
| `room_moves` | Property child of stay | Source and destination rooms must both belong to the stay's property. |
| `stay_occupants` | Property child of stay | Occupant guest must belong to the same property under current guest ownership. |
| `stay_rate_segments` | Property child of stay | Rate history is stay-scoped; preserve posted historical amounts. |

### Folios, payments and financial records

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `folios` | Property child of reservation | Reservation and folio ownership must be consistent; one folio per reservation is the current model. |
| `folio_windows` | Legacy/group-level payer window, child of folio | This distinct legacy model has no `stay_id`; do not conflate it with the stay-specific table. |
| `stay_folio_windows` | Property child of folio and stay | Stay-specific payer window; `stay_id` references `stays.id`. |
| `folio_items` | Property child of folio (optional stay link) | If both folio and stay are set, they must resolve to the same property and compatible reservation. |
| `folio_item_windows` | Property child/link of folio item and folio window | Both relationship paths must resolve to the same folio/property. |
| `folio_item_routing` | Property child/link of folio item and window | Routing target must belong to the same folio/property; verify idempotency and uniqueness semantics. |
| `payments` | Property child of folio | Payment and folio property must agree; protect idempotency and posting semantics. |
| `payment_refunds` | Property child of payment/folio | Refund must reference the original payment and matching folio/property; enforce refundable balance and authorization. |
| `invoices` | Property child of folio | Invoice and folio must share property; confirm numbering and lifecycle/immutability rules. |
| `deposit_transactions` | Property child of stay, optionally folio | Stay, folio, and actor must be consistent within the property. |
| `financial_transactions` | Property-owned financial root | `property_id` is authoritative; referenced folio/reservation must match it. Preserve idempotency and reversal invariants. |
| `ledger_entries` | Property child of financial transaction | Property is inherited through transaction; optional folio/stay references must match that property. Ledger rows should not be silently edited after posting. |
| `expenses` | Property-owned root | Expense number uniqueness should generally be property-scoped; actor must be authorized for the property. |
| `invoice_sequences` | Property-scoped state | One sequence per property; a sequence must never be shared across tenants. |
| `business_date_state` | Property-scoped state | Exactly one active state per property; all posting guards must resolve the owning property. |

### Restaurant / F&B

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `menu_items` | Property-owned root | Name uniqueness should normally be property-scoped. |
| `restaurant_orders` | Property-owned root | Folio, reservation, and creator must agree with order property. |
| `restaurant_order_items` | Property child of restaurant order | Menu item and folio item references must be property-consistent; preserve reversal history. |

### Inventory and purchasing

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `stock_items` | Property-owned root | SKU/name uniqueness should normally be property-scoped. |
| `stock_movements` | Property child of stock item | Business date and creator are checked against the stock item's property. |
| `suppliers` | Property-owned root under current ownership migration | Organization-wide supplier sharing is a possible future feature, but must be explicit. |
| `purchase_orders` | Property-owned root | Supplier, creator, business date, and related receipts must stay within the property. |
| `purchase_order_lines` | Property child of purchase order | Stock item and order must have the same property. This is the current Core table name. |
| `goods_receipts` | Property child of purchase order | Receipt property is inherited from its purchase order; received stock item references must match. This is the current Core/migration table name. |
| `goods_receipt_lines` | Property child of receipt/order | All order, receipt, and stock item links must resolve to the same property. This is the current Core/migration table name. |
| `stock_operations` | Property child of stock item | Validate operation references and business date using the stock item's property. |

### Housekeeping and maintenance

| Table | Proposed ownership | Notes / review requirement |
|---|---|---|
| `housekeeping_tasks` | Property child of room | Room determines property; assignment and creator must be authorized for that property. |
| `maintenance_blocks` | Property child of room | Room determines property; reporting/resolving users must be authorized; business date must match property state. |
| `room_inspections` (if present in deployed schema) | Property child of room/task | Confirm exact table name and migration origin during full migration inventory. |
| `maintenance/task history tables` (if present) | Child of the authoritative task/request | Confirm exact table names from migrations before creating constraints. |

The `room_inspections` and maintenance/task history entries are inventory checks, not a claim that those exact tables exist in the current schema.

## 4. Naming and schema-source cautions

- The purchasing Core tables are `purchase_order_lines`, `goods_receipts`, and `goods_receipt_lines`—not `purchase_order_items`, `purchase_receipts`, or `purchase_receipt_items`. Keep documentation and future constraints aligned with the actual declarations.
- `folio_windows` and `stay_folio_windows` are distinct tables with different parent semantics: the legacy/group-level `folio_windows` has no `stay_id`; `stay_folio_windows` is stay-specific and references `stays.id`. Revision `0005_stay_folio_windows` creates/adopts the latter exact name. Keep both tables distinct; verify fresh-install and supported-upgrade schema parity before any DDL.
- Schema behavior is spread across Alembic, SQLAlchemy metadata declarations, legacy SQL, and SQLite runtime compatibility edits. Source-level inventory must include all of these paths.

## 5. Important gaps and design decisions

1. **Ownership columns are not enough by themselves.** A table with `property_id` can still reference a room, guest, folio, supplier, or reservation from another property unless the database constraints and application checks prevent it.
2. **Global uniqueness can break multi-property SaaS.** Review globally unique room numbers, room type names, guest/contact values, expense numbers, SKUs, menu names, and supplier identifiers. Scope uniqueness to the owning property or organization where appropriate, while retaining global uniqueness for truly global identity/slug fields.
3. **Child tables need a canonical ownership path.** Do not add redundant `property_id` to every child by default. For high-risk financial or high-volume tables, denormalization can be considered only with matching consistency constraints and a clear benefit.
4. **Identity is not authorization.** A valid user session is not permission to access every property in an organization. Every endpoint and background task must resolve an authorized property context.
5. **Guest sharing is an explicit product decision.** The current guest model is property-owned. Cross-property Guest 360 must not be implemented by simply allowing arbitrary cross-property foreign keys.
6. **Configuration has precedence and types.** Property override → organization default → documented platform fallback. Never store secrets in configuration rows; validate typed settings and audit sensitive changes.
7. **Historical finance is immutable by design.** Tax/service-charge/rate changes must not recalculate already-posted transactions. Cross-tenant access controls must cover reports, exports, backups, and asynchronous jobs as well as CRUD endpoints.
8. **Database parity matters.** Constraints and behavior need tests on SQLite and PostgreSQL where both are supported. PostgreSQL-only triggers must not be mistaken for portable enforcement.

## 6. Migration history observed

- `0020_multi_tenant_foundation` creates organization/property tenancy foundations.
- `0021_property_ownership` already attempts to add `property_id` to its declared root/state table lists. It intentionally aborts if legacy operational rows exist rather than guessing their tenant.
- `0022_property_config` adds organization settings and property branding.
- `0023_property_date_guards` adds PostgreSQL business-date guards for selected financial, restaurant, stock, purchasing, and housekeeping writes.

Therefore, the next task is **not** to blindly create another ownership migration. First reconcile the full database inventory with these existing revisions, confirm exact migration heads and deployed-schema assumptions, and identify unprotected relationships.

## 7. Required review before implementation

- [ ] Inventory every `op.create_table`, SQLAlchemy table, bootstrap-created table, and raw SQL-created table.
- [ ] For every table, record owner, parent path, tenant key (direct or inherited), foreign keys, unique constraints, indexes, and write endpoints.
- [ ] Trace each foreign key in child records and verify same-property/same-organization invariants.
- [ ] Identify global unique constraints that should be tenant-scoped.
- [ ] Audit direct ID lookups and all list/report/export/background-job queries for authorized property context.
- [ ] Decide roles scope and future cross-property guest-profile strategy.
- [ ] Write tests for cross-tenant read, create, update, delete, joins, and financial posting rejection.
- [ ] Review the design and diff before proposing any migration.
- [ ] Only after approval, prepare a separate migration proposal with safe backfill/abort behavior and SQLite/PostgreSQL tests.

## 8. Explicit non-goals

This document does not create migration 0024, change application code, assign legacy records to a tenant, provision cloud resources, connect to a database, or touch production data. Those steps require separate review and, for any production data operation, explicit approval.
