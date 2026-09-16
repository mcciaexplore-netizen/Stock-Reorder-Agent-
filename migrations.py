"""Versioned, additive migrations. Existing balances enter Main warehouse."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import uuid

VERSION = 3
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (username TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 kind TEXT NOT NULL DEFAULT 'warehouse', contact TEXT NOT NULL DEFAULT '');
INSERT OR IGNORE INTO locations(id,name) VALUES(1,'Main warehouse');
CREATE TABLE IF NOT EXISTS valuations (product_id INTEGER REFERENCES products(id), location_id INTEGER REFERENCES locations(id),
 qty INTEGER NOT NULL DEFAULT 0 CHECK(qty>=0), value INTEGER NOT NULL DEFAULT 0 CHECK(value>=0), PRIMARY KEY(product_id,location_id));
CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 code TEXT NOT NULL, expiry TEXT, warranty_until TEXT, UNIQUE(product_id,code));
CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 location_id INTEGER NOT NULL REFERENCES locations(id), qty INTEGER NOT NULL CHECK(qty>0), reference TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','released','fulfilled')), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversions (product_id INTEGER REFERENCES products(id), unit TEXT NOT NULL COLLATE NOCASE,
 factor INTEGER NOT NULL CHECK(factor>0), PRIMARY KEY(product_id,unit));
CREATE TABLE IF NOT EXISTS quotes (id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 product_id INTEGER NOT NULL REFERENCES products(id), reference TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>=0),
 min_qty INTEGER NOT NULL CHECK(min_qty>0), freight INTEGER NOT NULL CHECK(freight>=0), lead_days INTEGER NOT NULL CHECK(lead_days>=0),
 valid_until TEXT NOT NULL, terms TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bills (id INTEGER PRIMARY KEY, po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id), number TEXT NOT NULL COLLATE NOCASE, bill_date TEXT NOT NULL,
 freight INTEGER NOT NULL CHECK(freight>=0), tax INTEGER NOT NULL CHECK(tax>=0), state TEXT NOT NULL DEFAULT 'review',
 created_at TEXT NOT NULL, UNIQUE(supplier_id,number));
CREATE TABLE IF NOT EXISTS bill_lines (id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id),
 po_line_id INTEGER NOT NULL REFERENCES po_lines(id), qty INTEGER NOT NULL CHECK(qty>0), price INTEGER NOT NULL CHECK(price>=0),
 UNIQUE(bill_id,po_line_id));
CREATE TABLE IF NOT EXISTS attachments (id INTEGER PRIMARY KEY, entity TEXT NOT NULL, entity_id INTEGER NOT NULL,
 filename TEXT NOT NULL, mime TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL,
 extracted_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, actor TEXT NOT NULL,
 UNIQUE(entity,entity_id,sha256));
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, customer TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'open', budget INTEGER NOT NULL DEFAULT 0 CHECK(budget>=0));
CREATE TABLE IF NOT EXISTS job_usage (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 movement_id INTEGER NOT NULL UNIQUE REFERENCES movements(id), cost INTEGER NOT NULL CHECK(cost>=0));
CREATE TABLE IF NOT EXISTS loans (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 location_id INTEGER NOT NULL REFERENCES locations(id), holder_location INTEGER NOT NULL REFERENCES locations(id),
 qty INTEGER NOT NULL CHECK(qty>0), returned INTEGER NOT NULL DEFAULT 0 CHECK(returned>=0 AND returned<=qty),
 holder TEXT NOT NULL, due_date TEXT NOT NULL, reference TEXT NOT NULL, batch_id INTEGER REFERENCES batches(id));
CREATE TABLE IF NOT EXISTS recipes (product_id INTEGER REFERENCES products(id), component_id INTEGER REFERENCES products(id),
 qty INTEGER NOT NULL CHECK(qty>0), PRIMARY KEY(product_id,component_id), CHECK(product_id<>component_id));
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '',
 gstin TEXT NOT NULL DEFAULT '', state_code TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, customer_id INTEGER NOT NULL REFERENCES customers(id),
 kind TEXT NOT NULL CHECK(kind IN ('invoice','credit')), original_id INTEGER REFERENCES invoices(id),
 invoice_date TEXT NOT NULL, due_date TEXT NOT NULL, location_id INTEGER NOT NULL REFERENCES locations(id),
 snapshot TEXT NOT NULL, subtotal INTEGER NOT NULL, cgst INTEGER NOT NULL, sgst INTEGER NOT NULL, igst INTEGER NOT NULL,
 total INTEGER NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoice_lines (id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL CHECK(qty>0), price INTEGER NOT NULL CHECK(price>=0),
 tax_rate INTEGER NOT NULL CHECK(tax_rate>=0 AND tax_rate<=10000), hsn TEXT NOT NULL, description TEXT NOT NULL,
 unit TEXT NOT NULL, cost INTEGER NOT NULL, net INTEGER NOT NULL, cgst INTEGER NOT NULL, sgst INTEGER NOT NULL, igst INTEGER NOT NULL,
 original_line_id INTEGER REFERENCES invoice_lines(id), batch_id INTEGER REFERENCES batches(id));
CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 amount INTEGER NOT NULL CHECK(amount>0), reference TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS repairs (id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id),
 customer TEXT NOT NULL, problem TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', resolution TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (key TEXT PRIMARY KEY, category TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
 resolved_at TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sync_batches (id TEXT PRIMARY KEY, result TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def _migrate_v2(path):
    path = Path(path)
    db = sqlite3.connect(path, timeout=30)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version in (2, 3):
            return
        if version != 1:
            raise ValueError('Unsupported database version.')
        # A separate snapshot can restore the exact pre-upgrade database.
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
        backup = sqlite3.connect(path.with_name(path.name + '.before-v2-' + stamp + '.sqlite3'))
        try:
            db.backup(backup)
        finally:
            backup.close()
        db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
        if db.execute('PRAGMA user_version').fetchone()[0] in (2, 3):
            db.commit()
            return  # Another process completed the upgrade while this process waited for its lock.
        for table, definition in [
            ('movements', 'location_id INTEGER NOT NULL DEFAULT 1 REFERENCES locations(id)'),
            ('movements', 'batch_id INTEGER REFERENCES batches(id)'),
            ('movements', 'value_delta INTEGER NOT NULL DEFAULT 0'),
            ('products', "tracking TEXT NOT NULL DEFAULT 'none'"),
            ('products', "attributes TEXT NOT NULL DEFAULT '{}'"),
            ('products', "hsn TEXT NOT NULL DEFAULT ''"),
            ('products', 'tax_rate INTEGER NOT NULL DEFAULT 0'),
            ('products', 'min_order INTEGER NOT NULL DEFAULT 0'),
            ('products', 'pack_size INTEGER NOT NULL DEFAULT 1'),
            ('products', 'safety_stock INTEGER NOT NULL DEFAULT 0'),
            ('purchase_orders', "due_date TEXT NOT NULL DEFAULT ''")]:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')
        balances = db.execute('SELECT p.id,p.unit_price,COALESCE(SUM(m.delta),0) FROM products p LEFT JOIN movements m ON p.id=m.product_id GROUP BY p.id').fetchall()
        for pid, price, qty in balances:
            db.execute('INSERT INTO valuations VALUES(?,?,?,?)', (pid, 1, qty, (qty*price+500)//1000))
        db.execute("INSERT INTO settings VALUES('valuation_start',?)", (datetime.now(timezone.utc).isoformat(),))
        db.execute("INSERT INTO settings VALUES('workspace_id',?)", (uuid.uuid4().hex,))
        db.execute('PRAGMA user_version=2')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def migrate(path):
    from operations_schema import SCHEMA as operations_schema
    path = Path(path)
    with closing(sqlite3.connect(path, timeout=30)) as probe:
        version = probe.execute('PRAGMA user_version').fetchone()[0]
    if version == VERSION:
        return
    if version == 1:
        _migrate_v2(path)
    elif version != 2:
        raise ValueError('Unsupported database version.')
    db = sqlite3.connect(path, timeout=30)
    try:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
        with closing(sqlite3.connect(path.with_name(path.name + '.before-v3-' + stamp + '.sqlite3'))) as backup:
            db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0] == VERSION:
            db.commit()
            return
        statement = ''
        for line in operations_schema.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ''
        db.execute('PRAGMA user_version=3')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
