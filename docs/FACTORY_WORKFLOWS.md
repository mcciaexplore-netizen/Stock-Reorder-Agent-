# Customer commitments and factory workflows

## Start with the six new sidebar screens

| Screen | Main workflow |
| --- | --- |
| Customer orders | Prepare customer quotation → confirm order → partial deliveries → invoice each delivery |
| Work orders | Plan output and operator → release → record material WIP and costs → partial / final output |
| Material planning | Net confirmed commitments and open work orders against free stock and dated supplies |
| Quality inspections | Quarantine → accept / reject → rework and reinspection or disposal |
| Job-work tracking | Record material owner → inward / outward challans → partial returns and reconciliation |
| Production costs | Record scrap / recovery → compare consumption and cost with the saved production plan |

Create customers in **Sales and invoices** and recipes in **Manufacturing and jobs** first.
The earlier quick-assembly and project-consumption workflows remain available. Do not
record the same physical production through both quick assembly and a work order.

## 1. Customer quotations, orders and delivery commitments

Quotations save customer/product details, quantities, agreed prices, tax rates, validity,
delivery date and notes. Confirming an unexpired quotation creates one sales order.
Quotation and order documents are printable HTML downloads. They are not tax invoices.

Orders show ordered, dispatched and pending quantities by product. A delivery can cover
part of an order; insufficient, reserved, expired or quarantined stock blocks the entire
delivery. Delivery notes retain the actual batch allocations and stock cost. A delivery
can be invoiced once, using its quantities and agreed prices, without another stock issue.
Payments and credit returns use the existing Sales and invoices screen. A credit return
does not reopen an order; create a replacement commitment if needed.

Delivery dates can be changed with a recorded reason. Cancelling an undelivered balance
preserves earlier deliveries and invoices. Open linked work orders must first be completed
or cancelled. Overdue commitments appear in Exceptions.

## 2. Production work orders and work in progress

A work order saves planned output, stock location, operator, due date, stages, estimated
overhead and a snapshot of the recipe and component prices. Later recipe edits do not
change an existing plan. A work order can link to a customer order line or make to stock.
Linked planned quantities cannot exceed that order line's production allocation.

Release the order, then record actual material consumption into WIP. These entries reduce
material inventory and carry its actual recorded cost into the job. Record labour hours
and hourly rates, machine hours/rates and other overhead separately. Material quantities
above the recipe allowance are permitted and visible as consumption variance.

Partial completion allocates the current unallocated WIP cost in proportion to output
quantity versus remaining planned output. Final completion receives all remaining WIP
cost. Record applicable costs and scrap before completion; closed jobs reject further
costs and output. Material consumption below the recipe requires a variance explanation.
Only orders without actual material, cost or output entries can be cancelled.

Every work-order output enters final-inspection quarantine automatically. Completed
production and quality release are separate events. The operator/stage/due-date table
and Exceptions identify delayed open work.

## 3. Material requirements planning

The planning horizon includes confirmed orders' undelivered quantities and open work
orders' unconsumed materials. Existing work orders also supply their remaining scheduled
finished output, so their component requirements are not counted twice. Uncovered make
requirements expand through multiple recipe levels.

Demands consume shared available stock once, in due-date order. Availability excludes
reservations, quarantine, expiry and stock held at external locations. Only placed POs
with a delivery date on or before the requirement date reduce shortages. Later and
undated purchases are shown separately; draft and uncertain orders are not treated as
confirmed supply. The plan can be exported as CSV.

This release pools internal warehouses and uses work-order due dates for material demand.
It does not calculate machine capacity, routing lead-time offsets or guarantee that a
scheduled work order will finish. Arrange stock transfers and review capacity separately.
Planning is advisory; purchasing and production are created through their normal screens.

## 4. Quality inspection and rework

Purchase receipts can enter quarantine in the same transaction as receipt using the
inspection checkbox. Existing stock can be held for an incoming, production or final
check. Tracked products require an explicit batch/serial; a hold cannot overlap another
hold or consume reserved quantities.

Accepted plus rejected quantities must equal the quantity awaiting inspection. Accepted
stock is released, while rejected stock remains blocked. Rework retains the hold until
reinspection. Disposal records a stock movement and releases only the disposed portion
of the hold. Inspection measurements, observations, inspector and disposition history
are retained. Holds apply to direct movements, transfers, assemblies, work consumption,
reservations, order deliveries and invoices, including automatic batch allocation.

Checks apply to stock quantities; destructive test samples, defect-code catalogues,
machine measurements and laboratory integrations are not automated. For older quick
assembly or manual receipts, start an inspection explicitly when one is required.

## 5. Ownership-aware job work

Choose **company** or **customer** ownership when opening a job-work order.

- Company outward challans move stock, with its cost, to a dedicated location for that
  contract. Partial returns restore stock to the sending warehouse; confirmed consumption
  and scrap remove it from company inventory. Ordinary stock movements cannot bypass
  the contract's reconciliation screen.
- Customer inward challans add to a separate custody ledger. Sending material to a
  processor, receiving partial returns, recording consumption/scrap, and returning
  on-site material to the customer update that ledger only. Customer material does not
  become company-owned stock or enter inventory valuation.

Each material line shows total received/sent, held outside, on site, returned, consumed
and scrap. Events produce downloadable operational challans and a CSV history. Closure
requires every quantity to be returned, consumed or scrapped. Overdue unreconciled jobs
appear in Exceptions. Conversion of customer-owned inputs into different finished SKUs,
subcontractor service billing and statutory job-work filings need separate workflows.

## 6. Scrap and cost analysis

Scrap identifies a portion of material already consumed by a work order; it does not
deduct that raw material twice. Recoverable offcuts can be received as a separate product
with an entered recovery value. That value is transferred out of unallocated WIP and
cannot exceed it. Same-product recovery cannot exceed the recorded scrap quantity.

The report shows planned versus actual consumption, scrap, labour, machine costs,
overhead, recovery credits, finished-output cost and remaining WIP. While a job is open,
actual costs are to date and planned costs cover the whole job. The linked order value
minus recorded job costs is explicitly labelled a committed-value comparison, not
realised profit; final margin depends on costs, deliveries, credits and business expenses.

## Access, upgrade and sample data

Owners/managers can use all these workflows. Accountants manage customer quotations,
orders and delivery invoicing. Warehouse staff handle dispatch, production, quality and
job-work custody. Read-only users can review and download documents but cannot mutate
records. Every new mutation has an explicit service permission and audit entry.

Database version 3 is additive. An automatic `.before-v3-*.sqlite3` backup precedes
upgrade, and normal backup/restore includes all new tables. Quantity-changing operations
use a write lock, bounded integer quantities, validation and replay-safe operation IDs.

The demo launcher adds a repeatable operations pack: open quotation, partially delivered
order and invoice, partially completed work order, labour/machine costs, recovered
offcuts, rejected incoming material, and customer/company job-work examples. Reloading
or resuming the completed pack preserves subsequent demo edits. Production startup
does not seed these records.
