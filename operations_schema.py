"""Additive schema for order commitments and factory operations (version 3)."""

SCHEMA = """
CREATE TABLE customer_quotes (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer_id INTEGER NOT NULL REFERENCES customers(id),
 valid_until TEXT NOT NULL, delivery_date TEXT NOT NULL, notes TEXT NOT NULL, snapshot TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','converted','cancelled')), created_at TEXT NOT NULL);
CREATE TABLE customer_quote_lines (
 id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES customer_quotes(id),
 product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL CHECK(qty>0),
 price INTEGER NOT NULL CHECK(price>=0), tax_rate INTEGER NOT NULL CHECK(tax_rate BETWEEN 0 AND 10000),
 UNIQUE(quote_id,product_id));
CREATE TABLE sales_orders (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, quote_id INTEGER UNIQUE REFERENCES customer_quotes(id),
 customer_id INTEGER NOT NULL REFERENCES customers(id), delivery_date TEXT NOT NULL, notes TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'confirmed' CHECK(state IN ('confirmed','partial','fulfilled','cancelled')),
 snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE sales_order_lines (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id), product_id INTEGER NOT NULL REFERENCES products(id),
 qty INTEGER NOT NULL CHECK(qty>0), dispatched INTEGER NOT NULL DEFAULT 0 CHECK(dispatched BETWEEN 0 AND qty),
 price INTEGER NOT NULL CHECK(price>=0), tax_rate INTEGER NOT NULL CHECK(tax_rate BETWEEN 0 AND 10000), UNIQUE(order_id,product_id));
CREATE TABLE sales_dispatches (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, order_id INTEGER NOT NULL REFERENCES sales_orders(id),
 location_id INTEGER NOT NULL REFERENCES locations(id), reference TEXT NOT NULL, dispatch_date TEXT NOT NULL,
 invoice_id INTEGER UNIQUE REFERENCES invoices(id), created_at TEXT NOT NULL);
CREATE TABLE sales_dispatch_lines (
 id INTEGER PRIMARY KEY, dispatch_id INTEGER NOT NULL REFERENCES sales_dispatches(id),
 order_line_id INTEGER NOT NULL REFERENCES sales_order_lines(id), movement_id INTEGER NOT NULL UNIQUE REFERENCES movements(id));
CREATE TABLE work_orders (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, product_id INTEGER NOT NULL REFERENCES products(id),
 order_line_id INTEGER REFERENCES sales_order_lines(id), location_id INTEGER NOT NULL REFERENCES locations(id),
 planned INTEGER NOT NULL CHECK(planned>0), completed INTEGER NOT NULL DEFAULT 0 CHECK(completed BETWEEN 0 AND planned),
 operator TEXT NOT NULL, due_date TEXT NOT NULL, stages TEXT NOT NULL, stage_index INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'planned' CHECK(state IN ('planned','released','in_progress','completed','cancelled')),
 notes TEXT NOT NULL, planned_overhead INTEGER NOT NULL DEFAULT 0 CHECK(planned_overhead>=0), created_at TEXT NOT NULL);
CREATE TABLE work_material_plan (
 work_id INTEGER REFERENCES work_orders(id), product_id INTEGER REFERENCES products(id),
 per_unit INTEGER NOT NULL CHECK(per_unit>0), planned_qty INTEGER NOT NULL CHECK(planned_qty>0),
 price INTEGER NOT NULL CHECK(price>=0), PRIMARY KEY(work_id,product_id));
CREATE TABLE work_material_usage (
 id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES work_orders(id),
 movement_id INTEGER NOT NULL UNIQUE REFERENCES movements(id));
CREATE TABLE work_costs (
 id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES work_orders(id), kind TEXT NOT NULL,
 hours INTEGER NOT NULL CHECK(hours>=0), rate INTEGER NOT NULL CHECK(rate>=0), cost INTEGER NOT NULL CHECK(cost>=0),
 note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE work_outputs (
 id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES work_orders(id),
 movement_id INTEGER NOT NULL UNIQUE REFERENCES movements(id), note TEXT NOT NULL);
CREATE TABLE work_scrap (
 id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES work_orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL CHECK(qty>0), reason TEXT NOT NULL,
 recovered_product_id INTEGER REFERENCES products(id), recovered_qty INTEGER NOT NULL DEFAULT 0 CHECK(recovered_qty>=0),
 recovery_value INTEGER NOT NULL DEFAULT 0 CHECK(recovery_value>=0), movement_id INTEGER UNIQUE REFERENCES movements(id),
 created_at TEXT NOT NULL);
CREATE TABLE quality_inspections (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), location_id INTEGER NOT NULL REFERENCES locations(id),
 batch_id INTEGER REFERENCES batches(id), work_id INTEGER REFERENCES work_orders(id), stage TEXT NOT NULL,
 reference TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0), held INTEGER NOT NULL CHECK(held BETWEEN 0 AND qty),
 accepted INTEGER NOT NULL DEFAULT 0 CHECK(accepted>=0), disposed INTEGER NOT NULL DEFAULT 0 CHECK(disposed>=0),
 state TEXT NOT NULL DEFAULT 'awaiting' CHECK(state IN ('awaiting','rejected','rework','closed')), created_at TEXT NOT NULL,
 CHECK(held+accepted+disposed=qty));
CREATE TABLE quality_events (
 id INTEGER PRIMARY KEY, inspection_id INTEGER NOT NULL REFERENCES quality_inspections(id),
 action TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE jobwork_orders (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, owner TEXT NOT NULL CHECK(owner IN ('company','customer')),
 customer_id INTEGER REFERENCES customers(id), subcontractor TEXT NOT NULL,
 location_id INTEGER NOT NULL REFERENCES locations(id), holder_location INTEGER NOT NULL REFERENCES locations(id),
 due_date TEXT NOT NULL, reference TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),
 created_at TEXT NOT NULL, CHECK(owner='company' OR customer_id IS NOT NULL));
CREATE TABLE jobwork_materials (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobwork_orders(id), product_id INTEGER NOT NULL REFERENCES products(id),
 batch_id INTEGER REFERENCES batches(id), qty INTEGER NOT NULL CHECK(qty>0), outside INTEGER NOT NULL CHECK(outside>=0),
 returned INTEGER NOT NULL DEFAULT 0 CHECK(returned>=0), consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed>=0),
 scrap INTEGER NOT NULL DEFAULT 0 CHECK(scrap>=0), CHECK(outside+returned+consumed+scrap<=qty));
CREATE TABLE jobwork_events (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE, material_id INTEGER NOT NULL REFERENCES jobwork_materials(id),
 action TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0), reference TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX quality_stock ON quality_inspections(product_id,location_id,batch_id);
CREATE INDEX work_usage ON work_material_usage(work_id);
CREATE INDEX dispatch_order ON sales_dispatches(order_id);
"""
