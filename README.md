# Stocklist

General inventory, purchasing, sales and operations software for one MSME business with multiple stock locations. Runs locally with Streamlit and SQLite.

## Start

Requires Python 3.11+. Direct dependencies are pinned; pip resolves transitive dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open `http://127.0.0.1:8501`. On macOS/Linux use `.venv/bin/python`. The server binds to localhost.

**Create your owner account on the first visit.** Use a password of at least twelve characters. No production credentials are preconfigured. In **Settings**, enter business details, optional GST details and purchase budget, then create staff accounts. Roles are owner, manager, purchaser, warehouse, accountant and viewer.

## Implemented modules

- Products, suppliers, variant SKUs, custom fields and barcode search.
- Warehouses, shops, subcontractor/consignment stock, transfers and reservations.
- Stock movements/counts, alternate units, batches, expiry and serial tracking.
- Bills of materials, kit assembly, internal work, overhead and job material use.
- Replenishment using stock, orders, reservations, consumption, lead time, MOQ and packs.
- Quotations, price history, approval budgets, POs and partial/full receiving.
- Supplier-bill verification and landed-cost comparison.
- Customer invoices, configured GST tax splits, linked credit returns and payments.
- Customer quotations, confirmed sales orders, delivery commitments, partial delivery notes and delivery invoicing.
- Work orders with operators, stages, partial output, material WIP, labour and machine costs.
- Multilevel material planning with shared stock allocation, dated purchases and scheduled work-order output.
- Incoming / work / final quality checks, quarantine, rework and rejected-stock disposal.
- Customer-owned material custody, company material held outside, challans and partial outside-work reconciliation.
- Scrap / recoverable offcuts, planned-versus-actual consumption and work-order cost analysis.
- Attachments, local text recognition, returnable goods, warranties and repairs.
- Local exceptions, valuation, supplier, margin and job-cost reports.
- Accounting CSV, manual/automatic backups, offline entry and English/Hindi navigation.

See the [full feature matrix and precise boundaries](docs/IMPLEMENTATION.md).
See the [connected order-to-work workflow](docs/FACTORY_WORKFLOWS.md) for the advanced operations modules.

For a separate sample business, run `python scripts/demo_preview.py`, then choose **Owner demo**, **Warehouse demo**, **Accountant demo**, or **Read-only demo** on the sign-in screen. It includes products for trading, assembly and service jobs, BOMs, work orders, customer jobs, multiple stock locations, batches/serials, purchase orders at different stages, supplier bills, invoices/payments/returns, and repair/returnable examples. All contacts and records are fictional; email sending is disabled.

Each normal demo launch creates a fresh temporary database. To keep your demo edits, use `python scripts/demo_preview.py --resume "<printed path to demo-access.json>"`. Loading the sample pack again does not reset stock, duplicate transactions, or overwrite later edits. The access file contains credentials generated for this demo and must stay with its database. The shortcut buttons only appear when that file is explicitly configured and matches the database and workspace identity. They use ordinary authenticated role permissions. Use the normal startup command above for persistent business data; it has no demo shortcuts by default.

## Common Business Walkthrough

1. **Import and backup:** preview the sample or your Excel/CSV. Review mappings and opening stock, then import. Existing SKUs are rejected.
2. **Products:** add materials and finished SKUs. For new batch/serial products, start with zero opening stock, configure **Tracking and units**, create batches/serials, then receive goods.
3. **Locations and reservations:** create warehouses, shops, service sites or outside-party locations and transfer stock to where it is held. Transfers preserve ownership and cost.
4. **Assembly and jobs:** select a finished product or kit, components and quantities per finished unit. Save the bill of materials.
5. Record completed assembly, kit preparation or production at the correct location with any labour/subcontracting overhead. Components are consumed and finished stock is received atomically; shortages block the whole action.
6. For services/projects, create a job and record material use. Do not record components already consumed by assembly a second time.
7. Compare quotations, prepare/approve POs, record placement and receive goods into the correct location. Enter actual receipt freight to include it in stock cost.
8. **Quotations and bills:** record supplier bills and resolve order/receipt/price discrepancies before acceptance.
9. **Sales and invoices:** dispatch stock, download printable invoices, record payments and receive invoice-linked returns.
10. Use **Exceptions** and **Reports** to review deliveries, expiry, payments, job overruns and stock costs.

## Stock and money

Quantities have three decimal places; prices have two. Movements are append-only. Location/batch balances cannot become negative. Physical counts reject stock changes since the count began. Alternate units convert into a permanent base unit without silent precision loss.

Dispatch selects the earliest unexpired batch when none is chosen. Expired items can be disposed of or returned explicitly. Reserved stock must be released or fulfilled before ordinary dispatch. External stock remains owned but is excluded from immediately available internal stock for replenishment.

Valuation uses moving weighted-average cost per location. Receipt cost includes allocated freight; production cost includes materials plus entered overhead. Supplier bill acceptance does not change stock cost a second time. Tax recoverability is not inferred.

The operator configures/checks GST rates, HSN and place of supply. Invoice documents implement domestic forward-charge goods with CGST/SGST/UTGST or IGST splits. The software does not register e-invoices, generate e-way bills or file returns. Accounting CSV is a generic handoff, not a live provider connection.

## Documents and offline work

Attach PDF, PNG, JPEG or UTF-8 text (up to 10 MB) to products, POs, bills, jobs, invoices or repairs. Files are included in database backups. PDF text is extracted locally. Image text recognition uses Windows OCR or local Tesseract (`TESSERACT_PATH`). Review extracted text against the original before entering financial values.

Download the **Offline entry** HTML sheet and open it on a phone/laptop. It stores movement entries on that device. Export the JSON queue, upload it in Stocklist, preview and confirm, then inspect each row's result. Applied IDs never apply twice. Failed rows do not alter stock and remain retryable. Keep the queue until every row is accounted for.

Download a fresh offline sheet after catalogue/location changes. Keyboard barcode scanners act as normal input. Camera scanning needs browser `BarcodeDetector` support and camera availability. Offline entry cannot guarantee availability until replay.

## Email

Set `GMAIL_USER` and `GMAIL_APP_PASSWORD` in `.env`. Live sending requires exact PO approval and separate confirmation. Dry previews never send. Revisions clear approval. Uncertain delivery requires checking the mailbox/supplier before recording an outcome or retrying. A crashed `sending` attempt can be reconciled after five minutes.

Email/AI credentials are unnecessary for inventory, local invoices, assembly/work orders or recording orders placed by phone. Exception alerts remain in the local inbox.

## Backups and upgrades

Default database: `data/stocklist.sqlite3`, configurable using `DATABASE_PATH`. Version-1 databases upgrade automatically after saving `.before-v2-*.sqlite3`. Version 3 adds the advanced operations tables after saving a `.before-v3-*.sqlite3` snapshot. Existing stock enters Main warehouse during the version-1 upgrade; its opening cost uses the current product price because the prototype did not retain historical receipt costs. Later upgrades preserve recorded quantities, valuations and history. Original movement history, workbook and CSV are preserved.

Owners can download complete backups in **Import and backup**. Enable automatic local backups in **Settings**. Checks run every sixty seconds while an owner's app is open; a backup runs only when its configured interval is due. To keep checks running with the browser closed:

```powershell
python maintenance.py --interval 300
```

The worker requests owner credentials and writes backups beside the database in `backups/`. Optional `STOCKLIST_USERNAME` and `STOCKLIST_PASSWORD` environment variables support unattended configuration; keep them private. It does not install an OS startup task. Copy backups to another device to protect against machine loss.

```powershell
python agent.py --backup stocklist-backup.sqlite3
python agent.py --restore stocklist-backup.sqlite3 --confirm-restore
```

**Stop every app/worker before restoring.** Restore validates integrity, schema and references, retains the previous database and replaces the active file. It runs under the local filesystem owner's authority. Reconcile activity after an old snapshot: restore cannot undo emails or physical movements. Backups contain attachments and password hashes.

## CLI and tests

```powershell
python agent.py --file inventory.xlsx
python agent.py
python agent.py --no-dry-run
python agent.py --explain
python -m unittest discover -s tests -v
```

After owner setup the CLI requires login. Live mode also requests purchase approval. Optional `--explain` needs `GROQ_API_KEY` and sends recommendation quantities for read-only explanation; AI cannot approve, send or change stock.

Tests use temporary databases and mocked email. They cover core rules, migrations, access control, production, tracking, bill matching, exact credits, offline replay, backups and Streamlit workflows. They never send supplier email or modify the sample workbook.

## Source map

| Files | Responsibility |
|---|---|
| `streamlit_app.py`, `app_pages/` | Login, navigation and screens |
| `stocklist.py`, `inventory.py` | Core ledger, purchasing, numbers and imports |
| `inventory_ops.py` | Locations, tracking, reservations, production and jobs |
| `purchasing.py`, `sales.py` | Quotations, bills, documents, invoices and credits |
| `workspace.py`, `security.py`, `migrations.py` | Reports, exceptions, accounts, settings and upgrades |
| `offline.py`, `assets/offline.html` | Offline entry and reviewed replay |
| `agent.py`, `maintenance.py`, `tools.py` | CLI, periodic checks and mail transport |
| `scripts/ocr_windows.ps1` | Local Windows text recognition |

The application supports one business per database. Internet hosting, tenant isolation and live government/accounting integrations require separate setup.
