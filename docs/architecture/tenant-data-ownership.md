# PMS tenant data ownership inventory

**Baseline audited:** `main` at `fedd26e9cc3a1eb09c0990749e18ee552b17ca3d`  
**Scope:** current SQLAlchemy models, tenancy/configuration models, route-defined SQLAlchemy tables, and migrations through `0023_property_scoped_business_date_guards`.  
**Status:** design/audit artifact only. No schema migration is proposed by this document.

## Ownership vocabulary

- **Organization-owned:** owned by an organization and shared only by properties in that organization.
- **Property-owned:** the row has an authoritative `property_id`; every read and mutation must be scoped to a property authorized for the acting user.
- **Child-owned:** ownership is inherited from a parent record (for example, a folio item belongs to the property of its folio). Child IDs must never be treated as authorization by themselves. Validate the complete parent chain and same-property links before reading or writing.
- **Shared/platform:** cross-property identity/reference/control data. Shared does not mean publicly readable or writable. Access is still authenticated and controlled.

## Current table inventory

The classification below describes intended authority, not a claim that every route currently enforces it. A table that lacks its own `property_id` is especially dependent on its parent joins and route guards.

| Table | Intended owner | Authoritative scope / parent | Audit notes |
|---|---|---|---|
| `organizations` | Organization-owned | Organization ID | Tenant root; inactive organizations must not resolve. |
| `organization_settings` | Organization-owned | `organization_id` | Only organization-scope access may update. |
| `properties` | Organization-owned | `organization_id` | Property is the operational boundary; code/slug uniqueness is per organization. |
| `property_settings` | Property-owned | `property_id` | Unique per property/key; allow-listed typed keys only. |
| `property_branding` | Property-owned | `property_id` | One row per property; presentation data only. |
| `property_user_access` | Child-owned | User + property | Explicit membership/access grant; organization membership alone must not silently grant access to every property. |
| `roles` | Shared/platform | Role catalog | Current role names are globally unique. If role definitions become tenant-configurable, split platform roles from organization role definitions in a designed migration. |
| `users` | Shared/platform identity | User ID + explicit property access | Username is globally unique; tokens identify the user, not an authorized property. Current role is re-read from DB. Consider organization-specific identities only as a future explicit design decision. |
| `room_types` | Property-owned | `property_id` | Name uniqueness is currently global; design target is property-scoped uniqueness before any constraint migration. |
| `rooms` | Property-owned | `property_id` | Room number is currently globally unique; design target is property-scoped uniqueness. Room type must belong to the same property. |
| `guests` | Property-owned | `property_id` | Guest identity/profile is currently property-specific; do not infer cross-property sharing from matching names/phones. |
| `reservations` | Property-owned | `property_id` | Guest, room assignments, and any stay references must match this property. |
| `reservation_rooms` | Child-owned | Reservation + room | Both referenced rows must belong to the same property as the reservation. |
| `reservation_splits` | Child-owned | Source + destination reservation | Both reservations must share property; creator is an identity reference, not an ownership grant. |
| `folios` | Child-owned | Reservation | Folio property is derived through reservation; unique reservation relationship must remain intact. |
| `folio_items` | Child-owned | Folio; optional stay | Folio and stay must resolve to the same property. |
| `payments` | Child-owned | Folio | Payment reads/writes require authorized folio property and financial permission. |
| `payment_refunds` | Child-owned | Payment + folio | Payment and folio must be same-property; amount/reversal and audit invariants must be atomic. |
| `folio_item_windows` | Child-owned | Folio item + folio window | Both parents must belong to the same property. |
| `folio_windows` | Child-owned | Stay/reservation (verify full model path) | Must not be addressable by ID without parent ownership validation. |
| `invoices` | Child-owned | Folio + reservation | Both parents must share property; invoice number generation must be property-scoped. |
| `invoice_sequences` | Property-owned | `property_id` | One sequence per property; never a singleton/global sequence. |
| `stays` | Child-owned | Reservation + room + guest | All referenced records must match reservation property. |
| `stay_occupants` | Child-owned | Stay + guest | Occupant guest must match stay/reservation property. |
| `stay_rate_segments` | Child-owned | Stay | Rate/discount changes need permission, reason, audit, and financial reconciliation. |
| `room_moves` | Child-owned | Stay + source/destination rooms | Both rooms must belong to the stay property; reject unavailable/dirty/out-of-order destinations. |
| `deposit_transactions` | Child-owned | Stay + optional folio | Stay, folio, user and ledger effects must be property-consistent and atomic. |
| `financial_transactions` | Property-owned | `property_id` plus optional folio/reservation | Transaction number and idempotency uniqueness are currently globally constrained in the ORM; consider property-scoped unique constraints and legacy-key compatibility in a later migration plan. |
| `ledger_entries` | Child-owned | Financial transaction; optional folio/stay | Parent transaction, folio, and stay must all resolve to the same property. Balanced postings/reversals are mandatory. |
| `expenses` | Property-owned | `property_id` | Expense number is currently globally unique; target property-scoped uniqueness. |
| `business_date_state` | Property-owned | `property_id` | Exactly one current state per property; closing one property must not lock another. |
| `audit_logs` | Property-owned | `property_id` | Append-only operational evidence; do not log secrets, credentials, or unnecessary guest document data. |
| `booking_groups` | Property-owned | `property_id` | Every linked reservation and primary guest must be in the same property. |
| `group_reservations` | Child-owned | Booking group + reservation | Enforce same-property membership on create and replay/read. |
| `menu_items` | Property-owned | `property_id` | Menu item name is currently globally unique; target property-scoped uniqueness. Stock item reference must be same-property. |
| `restaurant_orders` | Property-owned | `property_id` | Folio and reservation must be same-property; order number currently globally unique. |
| `restaurant_order_items` | Child-owned | Restaurant order + menu item | Menu item, stock reference and folio item must be same-property and consistent. |
| `stock_items` | Property-owned | `property_id` | SKU/name are currently globally unique; target property-scoped uniqueness. |
| `stock_movements` | Child-owned | Stock item | Business date, item, and actor must be scoped to the item's property. |
| `housekeeping_tasks` | Child-owned | Room | Property is derived through room; assignment/completion actors must be authorized for the same property. |
| `maintenance_blocks` | Child-owned | Room | Property is derived through room; maintenance block must not cross property boundary. |
| `suppliers` | Property-owned | `property_id` | Supplier code is currently globally unique; target property-scoped uniqueness. |
| `purchase_orders` | Property-owned | `property_id` + supplier | Supplier must be in same property; approval/receiving requires separate role controls. |
| `purchase_order_lines` | Child-owned | Purchase order + stock item | Both parents must belong to order property. |
| `goods_receipts` | Child-owned | Purchase order | Receipt belongs to the order property and must be idempotent. |
| `goods_receipt_lines` | Child-owned | Goods receipt + purchase order line/stock item | All referenced records must resolve to the same property. |

## Shared/global uniqueness that needs a deliberate follow-up

The current ORM declares globally unique names/numbers for several property-owned entities: `room_types.name`, `rooms.number`, `expenses.expense_no`, `financial_transactions.transaction_no`, `financial_transactions.idempotency_key`, `menu_items.name`, `restaurant_orders.order_no`, `stock_items.sku`, `stock_items.name`, and `suppliers.code`. The schema target should be uniqueness within the owning property, except where a true platform-wide identifier is intentionally required. Before changing these constraints, inventory existing duplicates, define idempotency-key compatibility, and test both PostgreSQL and SQLite behavior. Do not change these constraints ad hoc.

## Enforcement rules

1. Resolve the authenticated user and authorized property on every request; never trust a property ID supplied by the client without checking `property_user_access` and active organization/property status.
2. Scope parent queries by property before loading or mutating a child. Validate every foreign-key hop, including both source and destination records for transfers, splits, refunds, and group links.
3. Use one transaction for domain changes, ledger/payment/deposit effects, and the corresponding audit event. Denials and validation failures must leave no business writes.
4. Replays must check both property scope and idempotency payload/fingerprint before returning an earlier result.
5. Shared identity is not tenant authorization. Re-read active user/role state from the database; never authorize based on JWT role claims alone.
6. Keep audit records property-scoped. A denial may be security-logged separately, but must not create misleading successful business audit entries.
7. Every new table must be added to this inventory and to a metadata-backed ownership contract test in the same PR as its model/migration.

## Audit findings / limitations

- Migrations `0020`–`0023` establish organization/property/access, property ownership, configuration/branding, and property-scoped business-date guards. No new migration is included in this PR.
- Configuration resolution already implements platform defaults → organization defaults → property override; `null` property values fall back.
- Existing test suites cover tenancy foundations, configuration isolation, authorization helpers, and PostgreSQL cross-property cases. That is not proof every registered legacy route is safe. Route registration and overlapping legacy/completion financial handlers must remain part of the security gate.
- This is a code-derived ownership contract, not a certification that all enforcement is complete. The front-desk acceptance and cloud recovery gates remain open until evidence is recorded.
