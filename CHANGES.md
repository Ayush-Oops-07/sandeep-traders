# Sandeep Traders — Fixes Implemented

## ISSUE 1: Payment Receive / Payment Give

**New table** `payment_transactions` (database.py):
id, customer_id, payment_type (RECEIVED/GIVEN), amount, payment_mode,
reference_no, note, transaction_date, ledger_entry_id, created_by, created_at.

**New blueprint** `blueprints/payments.py` — `POST/GET /api/payments/`,
`PUT /api/payments/<id>`, `DELETE /api/payments/<id>`. Every payment
transaction automatically creates/updates/deletes a mirrored `LedgerEntry`
(Payment Receive = Credit, Payment Give = Debit) and triggers a full ledger
recalculation, then returns the new balance.

**New UI**: "Payment Receive" / "Payment Give" buttons on the Customer
Dashboard header and on each customer's ledger page. Clicking opens a modal
(`#modal-quick-payment` in templates/index.html) with customer search
(reuses the existing live party-search component), amount, payment mode
(Cash/UPI/Bank), reference number, note, transaction date, and Save.
JS logic in `static/js/app.js`: `openQuickPaymentModal()`, `saveQuickPayment()`.

## ISSUE 2: Backdated Entry Arithmetic Bug

**Root cause** (utils/helpers.py, old `recalculate_from_entry`): balances
were recalculated using `id` ordering instead of `transaction_date`
ordering. A backdated row (small date, large id because inserted later)
broke both the "find previous balance" lookup and left chronologically-later
rows (smaller id) un-recalculated — corrupting `Party.balance` itself, not
just display.

**Fix**: `recalculate_party_balance(db, party_id)` always rebuilds the
entire ledger from scratch in `entry_date ASC, id ASC` order. New public
entry point `recalculate_customer_ledger(customer_id, db=None)` matches the
spec's requested signature and is now called from every mutation path:
- Invoice create / edit / delete / cancel (`blueprints/invoices.py` —
  edit, delete, and cancel endpoints were also missing entirely and have
  been added, since the frontend already called them)
- Payment create / edit / delete (`blueprints/payments.py`)
- Manual debit/credit add / edit / delete (`blueprints/ledger.py`)
- Opening balance change (`blueprints/parties.py`)

`recalculate_from_entry()` is kept as a backward-compatible wrapper that
now also performs the full rebuild, so no caller was missed.

**Centralized dashboard source**: new `get_customer_ledger_summary()` in
utils/helpers.py and `GET /api/parties/<id>/summary` endpoint. The
per-customer ledger page's summary cards (Total Sales, Total Payments,
Current Balance) now read from this endpoint instead of re-summing raw
ledger rows in JavaScript (the old client-side code incorrectly counted
Payment Given debits as "sales" — fixed as part of this same requirement).

## Files changed
- `database.py` — added `PaymentTransaction` model + enum
- `utils/helpers.py` — rewrote balance recalculation, added
  `recalculate_customer_ledger`, `get_customer_ledger_summary`
- `blueprints/payments.py` — **new file**, full payment CRUD
- `blueprints/invoices.py` — added edit/delete/cancel endpoints, switched
  to centralized recalculation
- `blueprints/ledger.py` — switched to centralized recalculation
- `blueprints/parties.py` — added `/summary` endpoint, switched to
  centralized recalculation
- `app.py` — registered `payments_bp`
- `templates/index.html` — Payment Receive/Give buttons, new modal
- `static/js/app.js` — modal logic, centralized summary card fetch
- `migrate_payment_transactions.py` — **new file**, run once on deploy

## Deployment
```bash
pip install -r requirements.txt
python migrate_payment_transactions.py   # creates table + heals existing balances
```
The migration is idempotent and safe to re-run. It does not touch any
existing table other than recalculating `running_balance`/`balance` columns
(which were already corrupted by the old bug for anyone hit by it).

## Verified
- Spec's worked example (₹5,000 received 04-Jun, ₹80,000 invoice 18-Jun →
  ₹75,000 final balance) reproduced exactly, in both API and live browser UI.
- Full regression suite (19+ checks: party/invoice/ledger/payment CRUD,
  validation, dashboard) passes.
- Migration script verified to heal a simulated pre-existing corrupted
  database back to correct balances.

---

## ISSUE 3: New Invoice Opens With Previous Invoice Products

**Root cause** (`static/js/app.js`, old `openInvoiceModal`): only the JS
array `invRows` was reset; the actual DOM container (`#inv-items-body`)
was never cleared, so leftover row elements from the previous invoice
stayed visible and could duplicate on save.

**Fix**: new `resetInvoiceFormState()` clears the DOM container, the
`invRows` array, invoice number/date/due-date/notes, and all four total
displays back to ₹0 — called at the very start of every
`openInvoiceModal()` call (the single entry point for showing that
modal), so it covers close→reopen, save→create-another, and switch
customer. Browser refresh is a non-issue since the SPA re-renders from
the template on load.

## ISSUE 4: Service Charges / Manual Amount Entry

**Schema** (`database.py`): `InvoiceItem.item_type` ("inventory" |
"service"), `InvoiceItem.is_manual_total` (bool), `Product.stock_qty`
(nullable — opt-in stock tracking, never forced on existing products).

**Backend** (`blueprints/invoices.py`, both create and edit): each line
is now processed per its `item_type`:
- `service` rows skip unit/qty/rate/GST/discount entirely, take a
  direct `amount`, are always `is_manual_total=True`, never touch the
  product catalog, and never deduct stock.
- `inventory` rows keep the qty×rate×(1-disc%)×(1+gst%) auto-calc, but
  accept a manually-typed `total` (flagged `is_manual_total`) which the
  backend stores verbatim and never silently overwrites.
- The invoice's grand total is now the straight sum of each line's
  actual `total` (whatever way it was derived), not a re-derived
  subtotal−discount+gst formula — so manual overrides are always
  respected exactly.
- Stock deduction only happens for inventory rows whose matched product
  has a non-NULL `stock_qty` (i.e. only for products where stock is
  actively being tracked).

**Frontend**: each invoice row card now has an Inventory/Service toggle
pill. Service mode shows just a description + Amount field (no red
mandatory markers for irrelevant fields). Inventory mode's Total field
is now a live-editable input (was a read-only div) — typing into it
marks the row "✎ manual" and the auto-calculator stops touching it
until quantity/rate are changed again. Applied identically to both the
New Invoice and Edit Invoice modals. Print/view rendering shows a
"SERVICE" tag next to charge lines and collapses their unit/qty/rate/
GST columns to "—".

**Migration**: `migrate_service_items.py` — idempotent `ALTER TABLE`
for the three new columns.

## ISSUE 5: Convert Existing Payment Into Invoice (+ Advance accounting)

**New table** `invoice_adjustments` (`database.py`, `InvoiceAdjustment`
model) — durable record linking a payment's ledger entry to an invoice,
storing how much of that payment was "applied" to it.

**New ledger entry types**: `advance_received`, `advance_paid`,
`adjustment` (in addition to the existing sale/payment/debit/credit/
opening). Payments are now auto-classified: a Payment Receive/Give
logged while the customer has no outstanding balance to apply against
is tagged `advance_received`/`advance_paid` (shown with a blue ADVANCE
tag in the ledger); once there's outstanding debt, it's tagged plain
`payment`. This is informational only — it never changes the debit/
credit math, which is still purely ledger-formula driven.

**New blueprint** `blueprints/adjustments.py` —
`POST/GET /api/adjustments/`, `DELETE /api/adjustments/<id>`. Since the
original payment and invoice ledger entries already make the running
balance arithmetically correct on their own, an adjustment doesn't add
another debit/credit — it creates a zero-value "adjustment" ledger
entry purely so the link is visible in the ledger timeline
("Payment adjustment vs Invoice #C-0001"), plus the durable
`InvoiceAdjustment` row the UI/reports can query. Validates the
adjustment amount never exceeds what's still unapplied on that payment
(supports partial adjustments across multiple invoices).

**New UI**: an "Adjust" button appears on every Payment Received row in
the ledger table. Opens a modal showing the payment, an amount field
(prefilled to the full payment, editable for partial adjustment), and a
toggle between "Existing Invoice" (dropdown of that customer's open
invoices) and "Create New Invoice" (inline description + amount, posts
a new service-type invoice on save, then adjusts against it
immediately). Worked examples from the spec verified exactly:
  - Payment ₹5,000 + Invoice ₹8,000 → adjust → Outstanding ₹3,000
  - Payment ₹5,000 + Invoice ₹4,000 → adjust → Advance ₹1,000 remains

**Orphan-link cleanup**: deleting a payment (via either the generic
ledger delete or the Issue-1 payment-transaction delete) now also
deletes any `InvoiceAdjustment` rows and their generated adjustment
ledger entries that reference it, so no dangling links are left behind.

**Migration**: `migrate_adjustments.py` — creates `invoice_adjustments`
(idempotent).

## Additional files (Issues 3-5)
- `blueprints/adjustments.py` — **new file**
- `migrate_service_items.py` — **new file**
- `migrate_adjustments.py` — **new file**
- `database.py` — `InvoiceAdjustment` model, `item_type`/
  `is_manual_total` on `InvoiceItem`, `stock_qty` on `Product`, new
  entry-type constants
- `blueprints/invoices.py` — service item + manual total handling in
  create/edit
- `blueprints/payments.py` — advance auto-classification
- `blueprints/ledger.py` — adjustment-link cleanup on delete
- `blueprints/dashboard.py` — advance receipts counted in collections
- `utils/helpers.py` — advance receipts/payments counted in summary
- `app.py` — registered `adjustments_bp`
- `templates/index.html` — redesigned invoice item cards, Adjust modal
- `static/js/app.js` — form reset, item-type toggle, manual total,
  Adjust modal logic
- `static/css/style.css` — item-type toggle, manual-total badge styles

## Deployment (all issues)
```bash
pip install -r requirements.txt
python migrate_payment_transactions.py
python migrate_service_items.py
python migrate_adjustments.py
```
All three migrations are idempotent and safe to run in any order /
re-run.

