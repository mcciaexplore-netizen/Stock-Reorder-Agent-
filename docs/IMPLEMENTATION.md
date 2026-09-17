# Stocklist — general inventory and operations

Current navigation has seven sections: Overview, Products, Stock, Purchases, Sales, Reports
and Settings. There is no "Show all tools" menu. Tracking, locations, suppliers/bills/inspections,
customer orders and import/backup open from their related sections; alerts open from Overview.
Work orders,
material planning, outside work tracking, cost analysis, assembly/jobs, Documents,
Offline entry, and Returnables and repairs
were removed from the menu. The implementation details below also document retained legacy
services and data; those eight screens are no longer offered by the main app. Quality checks
remain available because purchase receipts can place stock on hold pending inspection.

## Delivered feature matrix

One business per database, multiple owned-stock locations, INR prices and authenticated users. The original workbook and historical CSV remain unchanged. The earlier review PDF describes the original prototype, not this expanded implementation.

| Capability | Screen | Implementation |
|---|---|---|
| Accounts and roles | Setup; Settings | Owner, manager, purchaser, warehouse, accountant and viewer; service-level permission checks and revocable sessions |
| Products and variants | Products; Tracking and units | Separate variant SKUs, barcodes, categories, prices and arbitrary custom fields |
| Warehouses and external stock | Locations and reservations | Warehouses, shops, subcontractor and consignment locations; paired transfers preserve ownership and cost |
| Reservations | Locations and reservations | Block ordinary issues of reserved goods; release or dispatch |
| Movements and counts | Stock movements | Receipts, sales/issues, returns, damage and counts per location; stale counts are rejected |
| Alternate units | Tracking and units | Product-specific movement conversion into the base stock unit; rejects precision loss |
| Batches, expiry and serials | Tracking and units | Traceable movements; earliest-expiry dispatch; expired sales/consumption blocked; one item per serial |
| BOMs and kits | Assembly and jobs | Component quantities per output unit; prevents recursive recipes |
| Assembly and outside work | Assembly and jobs | Atomic component consumption and output receipt, including entered labour/subcontracting overhead |
| Job material use | Assembly and jobs | Materials and cost per customer/project/job; material budgets |
| Replenishment | Overview | Available internal stock, reservations, open orders, recent consumption, supplier lead time, safety stock, MOQ and pack rules |
| Approval budgets | Settings; Purchase orders | Monthly goods-value limit checked when approving a PO |
| Quotations and price history | Quotations and bills | Compare prices, freight, MOQ, delivery time, validity and terms; create a draft from a quote |
| Purchase lifecycle | Purchase orders | Drafts, revisions, approval, email/manual placement, due dates, cancellation and partial/full receipt |
| Purchase verification | Quotations and bills | Match billed quantities/prices against orders and received goods; cumulative accepted bills cannot exceed receipts |
| Landed cost | Goods receipts; bill review | Receipt freight allocated by goods value into stock cost; bill-level landed-cost comparison |
| Sales and tax documents | Sales and invoices | Customer invoices, entered GST rates, intra/inter-state tax splits, linked partial credit returns, payments and printable documents |
| Customer commitments | Customer orders | Quote validity, confirmed orders, delivery dates, partial deliveries, pending quantities and delivery-linked invoicing without a second stock issue |
| Work orders | Work orders | Saved recipe plan, operator and stages, partial completion, actual material WIP, labour and machine costs |
| Material requirements | Material planning | Multilevel recipes, chronological shared-stock allocation, dated incoming purchases and open-work-order supply/demand |
| Quality controls | Quality checks | Incoming / work / final checks, stock holds, accepted/rejected quantities, rework, reinspection and disposal |
| Ownership and outside records | Outside work tracking | Customer material custody separate from company stock; outside-party outward/inward records, partial returns and reconciliation |
| Cost analysis | Cost analysis | Scrap / recovery, actual labour/machine costs, recipe consumption variance, allocated output cost and remaining WIP |
| Attachments and scanning | Documents | Database-backed PDF/images/text; local PDF extraction, Windows OCR or optional Tesseract; review before financial entry |
| Returnables | Returnables and repairs | Holder, due date, outstanding balance and partial returns; ownership retained |
| Warranty and repair | Returnables and repairs | Serial warranty dates, customer faults and repair outcomes |
| Exceptions | Exceptions | Low stock, pending approvals, delivery uncertainty, overdue deliveries/payments/returnables, bill mismatches, expiry, price changes, job overruns and rejected imports |
| Reports | Reports | Moving-average stock value, no-use-in-30-days stock, supplier delivery times, invoice margins and job costs |
| Accounting export | Reports | Signed sales/credit rows and accepted supplier-bill CSVs for accountant/import mapping |
| Scheduled backups/checks | Settings; maintenance.py | Consistent snapshots, app-open periodic checks and a separate recurring worker |
| Offline and barcode entry | Offline entry | Self-contained HTML queue, keyboard barcode entry, supported-browser camera scanning and reviewed idempotent replay |
| Interface language | All screens | English-only navigation and forms; Unicode record fields |

## Data guarantees and migration

Schema version 2 upgrades version 1 additively, saving a `.before-v2-*.sqlite3` snapshot first. Schema version 3 adds customer commitments, work orders, quality holds and job-work custody, saving `.before-v3-*.sqlite3` before the upgrade. Legacy movement IDs, quantities, dates and reasons remain unchanged. Existing stock enters Main warehouse during the version-1 upgrade. Opening valuation uses quantity times the product's purchase price at that upgrade; historical costs missing from the prototype are not invented.

The append-only ledger records location, optional batch/serial and signed value changes. Moving weighted-average cost is maintained independently per location. Transfers carry exactly the outgoing recorded cost. Production consumes component cost and adds entered overhead to finished goods. Invoice-linked returns restore the originally allocated cost. Accepting a supplier bill never receives goods or capitalises freight a second time.

SQLite write transactions acquire a lock before balance/state checks. Transfers, production, receipts, invoices and credits roll back completely if any line is invalid. Permanent operation IDs prevent duplicate submissions and offline replays; altered payloads under a used ID are rejected. Quantities use integer milli-units and money uses integer paise. Batch splits and cumulative partial credits preserve rounded invoice totals and costs.

Purchase approval covers the exact recipient, document, revision and lines. Revisions clear approval. SMTP attempts are saved before sending, and ambiguous results cannot automatically retry. Only goods receipts increase on-hand stock.

## Access control

### Sample business and demo entry

`scripts/demo_preview.py` creates a separate temporary sample business with four role-specific login buttons: Owner, Warehouse, Accountant and Read-only. The 12-product sample pack covers materials, finished goods, two BOMs and production runs, three jobs, locations/transfers/reservations, quotations, four purchase orders, bill matching, customer invoices/payments/credits, batches/serials, repairs and returnables. Dates are anchored to the first sample load so upcoming/overdue examples remain consistent during retries. The pack uses the same services, permissions, costing and ledger checks as ordinary user actions.

The sample loader retains existing records, can resume an interrupted load, and skips a completed load so subsequent user edits survive a restart. `--resume <demo-access.json>` keeps the same demo. It does not recreate staff accounts that the owner has disabled. Every new demo has generated credentials stored in its local access file; none are embedded in application source. Demo shortcuts require an explicit `STOCKLIST_DEMO_ACCESS` file matching both the database path and its workspace ID, then use the normal password/session login. Disabled accounts and changed roles are excluded. The launcher disables outgoing email; default business startup exposes no demo shortcuts.

### Business accounts

First-run setup creates an owner; no default production password is shipped. Salted scrypt uses N=2^17, r=8, p=1. Sessions store token hashes, expire after eight hours and are revoked when user credentials, role or active status changes. Five failed logins lock the username for fifteen minutes. Mutations record the authenticated name instead of a supplied operator label.

Public business actions enforce role permissions. Normal database access requires a valid session once accounts exist. The local filesystem owner remains administrator of the database file. CLI operations request credentials; offline restore is a filesystem-owner recovery operation performed with all app/worker processes stopped. Backups include password hashes and attachments and must remain private.

## Explicit boundaries

- Advanced operations support work-order stages, operators, partial output, WIP, actual labour / machine costs, scrap recovery and quality checks. Finite capacity scheduling and payroll are not included. See [operations workflows](FACTORY_WORKFLOWS.md) for allocation rules.
- Company material at subcontractors remains owned stock. Customer-owned material is kept in a separate custody ledger and never increases company inventory value. Operational challans and reconciliation are supported; job-work tax filings are not automated.
- Kits are assembled from BOMs before sale. Purchase orders, invoices and BOMs use the base stock unit; alternate-unit conversion is available for stock movements.
- Configure tracking before receiving stock. Existing tracked history cannot be reclassified. Serial receipts are recorded one serial per action/line.
- Tax documents support the implemented domestic forward-charge goods workflow using operator-checked HSN, rates and place of supply. E-invoice/IRN registration, e-way bills, return filing, reverse charge and export-specific treatment are not included. Printed documents provide a signature field.
- Accounting handoff is generic CSV, not a live accounting-provider connector or full double-entry ledger. Supplier bill tax totals do not determine input-credit eligibility.
- OCR extracts text for review; it does not automatically map arbitrary supplier layouts into bill lines. Windows needs an OCR recognition language; other platforms need local Tesseract.
- Offline operation replays reviewed movement queues, not the entire database. Live availability is checked at replay. Camera scanning depends on browser support.
- Navigation, forms and validation use English. Record fields support Unicode text.
- Checks run while the app/worker runs. Alerts stay in the local inbox; no email/SMS/WhatsApp alert provider is configured. Backups are not copied off the machine automatically.
- This is one business per database. Multi-tenant hosting, TLS deployment, external accounting and government-service integrations require separate setup.

## Verification references

Factory workflow update, 16 September 2026: 86 distinct automated checks passed across
the regression run and focused follow-ups. The 82-test regression run identified two
backup-restore version checks that still accepted only the old schema; both were corrected
and their targeted reruns passed. Four additional checks cover nested material planning,
delivery batch allocations, interrupted/repeated operations-demo loading and the actual
partial-delivery/invoice forms. Other checks cover quarantine bypass prevention,
concurrent dispatch, role restrictions, customer ownership, cost conservation and migrations.
All six new populated screens passed the browser check, with no browser errors or page
overflow; the 390-pixel production-cost screen also passed. The demo now includes
customer commitments, partial production, quality holds, scrap recovery and job-work samples.

Demo update, 16 September 2026: six demo checks cover interrupted/repeated loading, preservation of existing data and later edits, access-file isolation, disabled accounts, role permissions, all four login buttons and populated screens. The nine existing UI checks were also exercised; targeted reruns passed after changing sign-out to a callback. A real-browser check passed for all four roles, logout, desktop and 390-pixel mobile layouts, and offline queue persistence, with zero browser errors. The running demo contains 22 products (including its original ten), four purchase orders, three sales invoices plus one credit note, and four jobs. Database integrity, foreign keys and ledger balances all passed.

Verified on 16 September 2026: all 62 automated tests passed. Desktop and 390-pixel mobile browser checks reported no browser errors or horizontal page overflow. Offline entries survived a browser reload. Windows OCR successfully extracted text from a sample image. The original workbook and purchase-log hashes match the pre-implementation backup. Live supplier email and external government/accounting services were not exercised.

Tests use temporary databases and mocked mail transport. They exercise migrations, role checks, revocation, transactions, concurrent stock issues, costing, traceability, production, bill matching, tax/credit rounding, offline replay, documents, backup/restore and actual Streamlit forms.

Implementation references: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) and [CBIC invoice particulars](https://taxinformation.cbic.gov.in/content-page/explore-rules/1000136/1000001). These inform implementation; they do not certify every business tax scenario.
