"""Transactional inventory, manufacturing and purchasing for one business and multiple locations.

All stock is derived from append-only movements. Quantities use integer milli-units;
prices use integer paise. SQLite serializes writes before checking balances or order state.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import os
import cloud_database
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

from inventory import (ValidationError, amount, email, inr, line_value, quantity,
                       scaled, text, validate_product)
from inventory_ops import InventoryOps, rounded
from security import Security, protect
from migrations import migrate, VERSION
from purchasing import Purchasing
from sales import Sales
from workspace import Workspace
from customer_orders import CustomerOrders
from production import Production
from quality import Quality
from jobwork import Jobwork


SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE,
 email TEXT NOT NULL DEFAULT '' COLLATE NOCASE, phone TEXT NOT NULL DEFAULT '',
 terms TEXT NOT NULL DEFAULT '', lead_days INTEGER NOT NULL DEFAULT 0 CHECK(lead_days>=0),
 version INTEGER NOT NULL DEFAULT 1, UNIQUE(name,email));
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, item_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
 item_name TEXT NOT NULL, unit TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
 barcode TEXT UNIQUE COLLATE NOCASE, supplier_id INTEGER REFERENCES suppliers(id),
 unit_price INTEGER NOT NULL CHECK(unit_price>=0), selling_price INTEGER NOT NULL CHECK(selling_price>=0),
 reorder_level INTEGER NOT NULL CHECK(reorder_level>=0), reorder_qty INTEGER NOT NULL CHECK(reorder_qty>=0),
 version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS purchase_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE,
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id), supplier_name TEXT NOT NULL,
 supplier_email TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN
 ('draft','approved','sending','sent','partial','received','cancelled','delivery_unknown')),
 revision INTEGER NOT NULL DEFAULT 1, subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
 approval_hash TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, approved_at TEXT,
 sent_at TEXT, actor TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS po_lines (
 id INTEGER PRIMARY KEY, po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id), item_code TEXT NOT NULL,
 item_name TEXT NOT NULL, unit TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0),
 price INTEGER NOT NULL CHECK(price>=0), received INTEGER NOT NULL DEFAULT 0 CHECK(received>=0 AND received<=qty),
 UNIQUE(po_id,product_id));
CREATE TABLE IF NOT EXISTS movements (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 delta INTEGER NOT NULL, kind TEXT NOT NULL, reason TEXT NOT NULL,
 reference TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS movements_product ON movements(product_id);
CREATE TABLE IF NOT EXISTS operations (
 token TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, entity TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (
 id INTEGER PRIMARY KEY, po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
 revision INTEGER NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, finished_at TEXT);
CREATE TRIGGER IF NOT EXISTS movements_no_update BEFORE UPDATE ON movements
 BEGIN SELECT RAISE(ABORT, 'Stock movements cannot be edited; record a correction.'); END;
CREATE TRIGGER IF NOT EXISTS movements_no_delete BEFORE DELETE ON movements
 BEGIN SELECT RAISE(ABORT, 'Stock movements cannot be deleted; record a correction.'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
 BEGIN SELECT RAISE(ABORT, 'Audit history cannot be edited.'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
 BEGIN SELECT RAISE(ABORT, 'Audit history cannot be deleted.'); END;
PRAGMA user_version=1;
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def actor_name(actor):
    return text(actor, 'Operator name', required=True, limit=100)


@protect
class Stocklist(Security, InventoryOps, Purchasing, Sales, Workspace, CustomerOrders, Production, Quality, Jobwork):
    def __init__(self, path, session_token=None):
        self.cloud = cloud_database.is_cloud(path)
        self.path = str(path) if self.cloud else Path(path)
        self.session_token = session_token
        self._initializing = True
        if self.cloud:
            cloud_database.initialize(self.path, self._empty_schema, VERSION)
            self._initializing = False
            if self.needs_setup():
                username = os.getenv('STOCKLIST_OWNER_USERNAME', '')
                password = os.getenv('STOCKLIST_OWNER_PASSWORD', '')
                if not username or not password:
                    raise ValidationError('Set STOCKLIST_OWNER_USERNAME and STOCKLIST_OWNER_PASSWORD in hosting settings to initialize the owner account.')
                try:
                    self.bootstrap(username, 'Business owner', password)
                except ValidationError:
                    if self.needs_setup():
                        raise
                finally:
                    self.session_token = session_token
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(True) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, VERSION):
                raise ValidationError('This database was created by a different app version.')
            if version == 0:
                # Keep first creation under the same lock as the version check. executescript
                # would commit the lock early, allowing another initializer to reset the version.
                statement = ''
                for line in SCHEMA.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ''
        migrate(self.path)
        self._initializing = False

    @staticmethod
    def _empty_schema():
        with tempfile.TemporaryDirectory(prefix='stocklist-schema-') as folder:
            local = Stocklist(Path(folder) / 'template.sqlite3')
            with closing(sqlite3.connect(local.path)) as db:
                return '\n'.join(db.iterdump())

    @contextmanager
    def connect(self, write=False):
        if not self._initializing:
            self.identity()
        db = cloud_database.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise ValidationError(f'Conflicting or invalid record: {exc}') from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _audit(db, actor, action, entity, detail):
        db.execute('INSERT INTO audit(created_at,actor,action,entity,detail) VALUES(?,?,?,?,?)',
                   (now(), actor_name(actor), action, str(entity), json.dumps(detail, ensure_ascii=False)))

    @staticmethod
    def _once(db, token, payload):
        token = text(token, 'Operation identifier', required=True, limit=200)
        previous = db.execute('SELECT * FROM operations WHERE token=?', (token,)).fetchone()
        fingerprint = digest(payload)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise ValidationError('This action has already been used with different values. Refresh and try again.')
            return json.loads(previous['result'])
        return None

    @staticmethod
    def _done(db, token, payload, result):
        db.execute('INSERT INTO operations VALUES(?,?,?)', (token, digest(payload), json.dumps(result)))
        return result

    @staticmethod
    def _product(db, product_id):
        row = db.execute('SELECT * FROM products WHERE id=?', (int(product_id),)).fetchone()
        if not row:
            raise ValidationError('Product no longer exists. Refresh the page.')
        return dict(row)

    @staticmethod
    def _balance(db, product_id):
        return db.execute('SELECT COALESCE(SUM(delta),0) FROM movements WHERE product_id=?', (product_id,)).fetchone()[0]

    def _movement(self, db, product_id, delta, kind, reason, reference, actor,
                  location_id=1, batch_id=None, unit_cost=None, total_cost=None, custody=False):
        from datetime import date
        product = self._product(db, product_id)
        location = self._location(db, location_id)
        if location['kind']=='jobwork' and not custody:
            raise ValidationError('Use job-work challans to change stock held for a subcontracting order.')
        local = self._local_balance(db, product_id, location_id)
        balance = local + delta
        if balance < 0:
            raise ValidationError('Insufficient stock at this location. This action would make stock negative.')
        if delta < 0 and balance < self._reserved(db, product_id, location_id):
            raise ValidationError('This stock is reserved. Release or fulfill the reservation first.')
        if delta < 0 and balance < self._reserved(db, product_id, location_id) + self._held(db, product_id, location_id):
            raise ValidationError('Stock is in quality quarantine. Complete inspection or rework before using it.')
        if balance > 10**12:
            raise ValidationError('Stock balance exceeds the supported range.')
        if product['tracking'] != 'none' and delta:
            batch = db.execute('SELECT * FROM batches WHERE id=? AND product_id=?',(batch_id,product_id)).fetchone()
            if not batch:
                raise ValidationError('Choose a batch / serial number for this tracked product.')
            batch_balance = self._local_balance(db, product_id, location_id, batch_id) + delta
            if batch_balance < 0:
                raise ValidationError('Insufficient stock in the selected batch / serial.')
            if delta < 0 and batch_balance < self._held(db,product_id,location_id,batch_id):
                raise ValidationError('This batch / serial is held in quality quarantine.')
            if delta < 0 and batch['expiry'] and batch['expiry'] < date.today().isoformat() and kind not in ('damage','supplier_return','adjustment','stock_count','transfer_out','loan_out','jobwork_return','jobwork_scrap'):
                raise ValidationError('Expired stock cannot be sold or consumed. Record damage or a return.')
            if product['tracking']=='serial':
                total = db.execute('SELECT COALESCE(SUM(delta),0) FROM movements WHERE batch_id=?',(batch_id,)).fetchone()[0]+delta
                if abs(delta)!=1000 or total not in (0,1000):
                    raise ValidationError('Each serial number represents exactly one item across all locations.')
        elif batch_id is not None:
            raise ValidationError('This product does not use batch tracking.')
        valuation = db.execute('SELECT qty,value FROM valuations WHERE product_id=? AND location_id=?',(product_id,location_id)).fetchone()
        old_value = valuation['value'] if valuation else 0
        if delta < 0:
            cost = old_value if -delta == local else rounded(old_value * -delta, local)
            value_delta = -cost
        else:
            value_delta = total_cost if total_cost is not None else line_value(delta,product['unit_price'] if unit_cost is None else unit_cost)
        if not 0 <= value_delta + old_value <= 10**12 or abs(value_delta) > 10**12:
            raise ValidationError('Stock valuation is outside the supported range.')
        db.execute('INSERT INTO valuations VALUES(?,?,?,?) ON CONFLICT(product_id,location_id) DO UPDATE SET qty=excluded.qty,value=excluded.value',
            (product_id,location_id,balance,old_value+value_delta))
        cur = db.execute('INSERT INTO movements(product_id,delta,kind,reason,reference,actor,created_at,location_id,batch_id,value_delta) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (product_id, delta, kind, reason, reference, actor_name(actor), now(),location_id,batch_id,value_delta))
        return cur.lastrowid

    def suppliers(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM suppliers ORDER BY name,email')]

    def save_supplier(self, name, address='', phone='', terms='', lead_days=0, *, actor,
                      supplier_id=None, version=None):
        name = text(name, 'Supplier name', required=True, limit=200)
        address = email(address)
        phone = text(phone, 'Phone', limit=60); terms = text(terms, 'Payment terms', limit=500)
        days = scaled(lead_days, 'Lead time', 1)
        if days > 3650:
            raise ValidationError('Lead time cannot exceed 3,650 days.')
        with self.connect(True) as db:
            if supplier_id:
                cur = db.execute('UPDATE suppliers SET name=?,email=?,phone=?,terms=?,lead_days=?,version=version+1 WHERE id=? AND version=?',
                                 (name, address, phone, terms, days, supplier_id, version))
                if not cur.rowcount:
                    raise ValidationError('Supplier changed in another session. Refresh before saving.')
            else:
                supplier_id = db.execute('INSERT INTO suppliers(name,email,phone,terms,lead_days) VALUES(?,?,?,?,?)',
                                         (name, address, phone, terms, days)).lastrowid
            self._audit(db, actor, 'supplier_saved', supplier_id, {'name': name, 'email': address})
        return supplier_id

    def products(self):
        with self.connect() as db:
            rows = db.execute("""SELECT p.*,s.name supplier_name,s.email supplier_email,
                COALESCE((SELECT SUM(delta) FROM movements m WHERE m.product_id=p.id),0) stock,
                COALESCE((SELECT SUM(l.qty-l.received) FROM po_lines l JOIN purchase_orders o ON l.po_id=o.id
                  WHERE l.product_id=p.id AND o.state IN ('sent','partial','sending','delivery_unknown')),0) incoming,
                COALESCE((SELECT SUM(l.qty-l.received) FROM po_lines l JOIN purchase_orders o ON l.po_id=o.id
                  WHERE l.product_id=p.id AND o.state IN ('draft','approved')),0) planned
                FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.item_name,p.item_code""").fetchall()
            return [dict(r) for r in rows]

    def save_product(self, raw, *, actor, token, product_id=None, version=None, opening=0, supplier_id=None):
        data = validate_product(raw)
        opening = scaled(opening, 'Opening stock')
        payload = ['product', data, product_id, version, opening, supplier_id, actor_name(actor)]
        with self.connect(True) as db:
            previous = self._once(db, token, payload)
            if previous is not None:
                return previous
            return self._done(db, token, payload,
                              self._save_product(db, data, actor, product_id, version, opening, supplier_id))

    def _save_product(self, db, data, actor, product_id, version, opening, supplier_id):
        values = (data['item_code'], data['item_name'], data['unit'], data['category'], data['barcode'] or None,
                  supplier_id, scaled(data['unit_price'], 'Purchase price', 100), scaled(data['selling_price'], 'Selling price', 100),
                  scaled(data['reorder_level']), scaled(data['reorder_qty']))
        if product_id:
            old = self._product(db, product_id)
            if old['unit'] != data['unit']:
                raise ValidationError('The stock unit cannot change after creation. Create a separate SKU for another unit.')
            if opening:
                raise ValidationError('Use a stock count or adjustment to correct existing stock.')
            cur = db.execute('UPDATE products SET item_code=?,item_name=?,unit=?,category=?,barcode=?,supplier_id=?,unit_price=?,selling_price=?,reorder_level=?,reorder_qty=?,version=version+1 WHERE id=? AND version=?',
                             (*values, product_id, version))
            if not cur.rowcount:
                raise ValidationError('Product changed in another session. Refresh before saving.')
        else:
            product_id = db.execute('INSERT INTO products(item_code,item_name,unit,category,barcode,supplier_id,unit_price,selling_price,reorder_level,reorder_qty) VALUES(?,?,?,?,?,?,?,?,?,?)', values).lastrowid
            self._movement(db, product_id, opening, 'opening', 'Opening balance', '', actor)
        self._audit(db, actor, 'product_saved', product_id, data)
        return product_id

    def import_products(self, records, *, actor, token):
        if not records:
            raise ValidationError('Nothing to import.')
        payload = ['import', records, actor_name(actor)]
        with self.connect(True) as db:
            previous = self._once(db, token, payload)
            if previous is not None:
                return previous
            count = 0
            for raw in records:
                data = validate_product(raw)
                if db.execute('SELECT 1 FROM products WHERE item_code=?', (data['item_code'],)).fetchone():
                    raise ValidationError(f'SKU {data["item_code"]} already exists. Import adds new products only; use product editing or a stock count for existing stock.')
                supplier_id = None
                if data['supplier_name']:
                    db.execute('INSERT OR IGNORE INTO suppliers(name,email) VALUES(?,?)', (data['supplier_name'], data['supplier_email']))
                    supplier_id = db.execute('SELECT id FROM suppliers WHERE name=? AND email=?', (data['supplier_name'], data['supplier_email'])).fetchone()[0]
                self._save_product(db, data, actor, None, None, scaled(raw.get('current_stock'), 'Opening stock'), supplier_id)
                count += 1
            self._audit(db, actor, 'inventory_imported', token, {'products': count})
            return self._done(db, token, payload, count)

    def move_stock(self, product_id, kind, value, reason, *, actor, token, reference='', expected_stock=None,
                   location_id=1, batch_id=None, unit='', unit_cost=None):
        kinds = {'receipt': 1, 'customer_return': 1, 'sale': -1, 'issue': -1,
                 'supplier_return': -1, 'damage': -1, 'adjustment': 1, 'stock_count': 1}
        if kind not in kinds:
            raise ValidationError('Choose a supported stock movement.')
        reason = text(reason, 'Reason', required=True, limit=500)
        reference = text(reference, 'Reference', limit=200)
        units = scaled(value, 'Quantity', signed=kind == 'adjustment')
        if not units and kind != 'stock_count':
            raise ValidationError('Quantity must be greater than zero (or signed for an adjustment).')
        payload = ['movement', product_id, kind, units, reason, reference, actor_name(actor), expected_stock,location_id,batch_id,unit,unit_cost]
        with self.connect(True) as db:
            previous = self._once(db, token, payload)
            if previous is not None:
                return previous
            units = self._converted(db,product_id,units,unit)
            delta = units * kinds[kind]
            if kind == 'stock_count':
                actual = self._local_balance(db, product_id,location_id,batch_id)
                if expected_stock is None or actual != expected_stock:
                    raise ValidationError('Stock changed since this count was opened. Refresh and verify the physical count again.')
                delta = units - actual
            if delta<0 and batch_id is None and self._product(db,product_id)['tracking']!='none' and kind not in ('stock_count','adjustment','damage'):
                movement = self._take(db,product_id,-delta,location_id,kind,reason,reference,actor)
            else:
                movement = self._movement(db, product_id, delta, kind, reason, reference, actor,location_id,batch_id,
                    scaled(unit_cost,'Receipt unit cost',100) if unit_cost is not None else None)
            self._audit(db, actor, kind, product_id, {'movement': movement, 'delta': delta, 'reference': reference})
            return self._done(db, token, payload, movement)

    def movements(self, product_id=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT m.*,p.item_code,p.item_name,p.unit FROM movements m JOIN products p ON p.id=m.product_id ' +
                    ('WHERE product_id=? ' if product_id else '') + 'ORDER BY m.id DESC', (product_id,) if product_id else ())]

    def audit(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC')]

    def recommendations(self):
        products = self.products()
        with self.connect() as db:
            recommendations = []
            for p in products:
                suggestion = self._reorder_suggestion(db,p)
                if suggestion:
                    recommendations.append(dict(p,**suggestion))
            return recommendations

    def _reorder_suggestion(self, db, product):
        from datetime import date, timedelta
        pid=product['id']
        available=self._available_internal(db,pid)
        outstanding=db.execute("""SELECT COALESCE(SUM(l.qty-l.received),0) FROM po_lines l JOIN purchase_orders o ON o.id=l.po_id
            WHERE l.product_id=? AND o.state IN ('draft','approved','sending','sent','partial','delivery_unknown')""",(pid,)).fetchone()[0]
        used=db.execute("""SELECT COALESCE(-SUM(delta),0) FROM movements WHERE product_id=? AND delta<0
            AND kind IN ('sale','invoice_sale','issue','job_issue','production_issue','order_dispatch','work_consumption','jobwork_consume') AND created_at>=?""",(pid,(date.today()-timedelta(days=30)).isoformat())).fetchone()[0]
        supplier=db.execute('SELECT lead_days FROM suppliers WHERE id=?',(product['supplier_id'],)).fetchone()
        lead=supplier['lead_days'] if supplier else 0
        level=max(product['reorder_level'],product['safety_stock']+(used*lead+29)//30)
        projected=available+outstanding
        if projected>=level:return None
        target=product['reorder_qty'] or (level*3+1)//2-projected
        target=max(target,product['min_order'])
        pack=product['pack_size']
        target=((target+pack-1)//pack)*pack
        return {'suggested_qty':target,'projected':projected,'effective_reorder_level':level,'available':available}

    def create_po(self, supplier_id, lines, *, actor, token, notes='', reorder=False):
        notes = text(notes, 'Order notes', limit=2000)
        payload = ['reorder' if reorder else 'po', supplier_id, [] if reorder else lines, notes, actor_name(actor)]
        with self.connect(True) as db:
            previous = self._once(db, token, payload)
            if previous is not None:
                return previous
            supplier = db.execute('SELECT * FROM suppliers WHERE id=?', (supplier_id,)).fetchone()
            if not supplier:
                raise ValidationError('Choose a supplier.')
            if reorder:
                lines = []
                for product in db.execute('SELECT * FROM products WHERE supplier_id=?', (supplier_id,)).fetchall():
                    suggestion=self._reorder_suggestion(db,product)
                    if suggestion:
                        lines.append({'product_id': product['id'], 'qty': quantity(suggestion['suggested_qty']), 'price': amount(product['unit_price'])})
                if not lines:
                    raise ValidationError('These items are already covered by stock or open orders. Refresh the recommendations.')
            po_id = db.execute('INSERT INTO purchase_orders(supplier_id,supplier_name,supplier_email,notes,created_at,actor) VALUES(?,?,?,?,?,?)',
                               (supplier_id, supplier['name'], supplier['email'], notes, now(), actor)).lastrowid
            number = f'PO-{datetime.now().strftime("%Y%m%d")}-{po_id:06d}'
            db.execute('UPDATE purchase_orders SET number=? WHERE id=?', (number, po_id))
            self._replace_lines(db, po_id, lines)
            self._audit(db, actor, 'po_created', number, {'lines': lines})
            return self._done(db, token, payload, po_id)

    def _replace_lines(self, db, po_id, lines):
        if not lines:
            raise ValidationError('Add at least one order line.')
        seen = set()
        db.execute('DELETE FROM po_lines WHERE po_id=?', (po_id,))
        for line in lines:
            product = self._product(db, line['product_id'])
            if product['id'] in seen:
                raise ValidationError('A product can appear only once in an order.')
            seen.add(product['id'])
            qty = scaled(line['qty'], 'Order quantity')
            price = scaled(line['price'], 'Unit price', 100)
            if qty <= 0:
                raise ValidationError('Order quantity must be greater than zero.')
            line_value(qty, price)
            db.execute('INSERT INTO po_lines(po_id,product_id,item_code,item_name,unit,qty,price) VALUES(?,?,?,?,?,?,?)',
                       (po_id, product['id'], product['item_code'], product['item_name'], product['unit'], qty, price))

    @staticmethod
    def _order(db, po_id):
        order = db.execute('SELECT * FROM purchase_orders WHERE id=?', (po_id,)).fetchone()
        if not order:
            raise ValidationError('Purchase order no longer exists.')
        order = dict(order)
        order['lines'] = [dict(r) for r in db.execute('SELECT * FROM po_lines WHERE po_id=? ORDER BY id', (po_id,))]
        order['total'] = sum(line_value(l['qty'], l['price']) for l in order['lines'])
        order['business'] = {r['key']:r['value'] for r in db.execute("SELECT * FROM settings WHERE key IN ('business_name','business_address')")}
        return order

    def order(self, po_id):
        with self.connect() as db:
            return self._order(db, po_id)

    def orders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM purchase_orders ORDER BY id DESC')]

    def revise_po(self, po_id, lines, notes, *, actor, revision):
        notes = text(notes, 'Order notes', limit=2000)
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] not in ('draft', 'approved') or order['revision'] != revision:
                raise ValidationError('This order changed or has already been placed. Refresh it before editing.')
            self._replace_lines(db, po_id, lines)
            db.execute("UPDATE purchase_orders SET state='draft',notes=?,revision=revision+1,subject='',body='',approval_hash='',approved_at=NULL WHERE id=?", (notes, po_id))
            self._audit(db, actor, 'po_revised', order['number'], {'previous_revision': revision})

    @staticmethod
    def draft_email(order):
        import config
        business = order.get('business', {})
        business_name = business.get('business_name') or config.BUSINESS_NAME
        business_address = business.get('business_address') or config.BUSINESS_ADDRESS
        subject = f'Purchase Order {order["number"]} - {order["supplier_name"]}'
        rows = []
        for line in order['lines']:
            rows.append(f'{line["item_name"]} [{line["item_code"]}]\n'
                        f'  {quantity(line["qty"])} {line["unit"]} × {inr(amount(line["price"]))} = {inr(amount(line_value(line["qty"], line["price"])))}')
        body = (f'Dear {order["supplier_name"]},\n\nPurchase Order: {order["number"]}\n'
                f'From: {business_name}\n{business_address}\n\n' + '\n\n'.join(rows) +
                f'\n\nOrder total: {inr(amount(order["total"]))}\n'
                'Amounts exclude tax and freight unless explicitly agreed.\n' +
                (f'\nNotes: {order["notes"]}\n' if order['notes'] else '') +
                '\nPlease acknowledge this order and confirm the expected delivery date.\n\n'
                f'Regards,\n{business_name}\n')
        return subject, body

    @staticmethod
    def _approval(order, subject, body):
        return digest([order['id'], order['revision'], order['supplier_email'], subject, body,
                       [(l['product_id'], l['qty'], l['price'], l['unit']) for l in order['lines']]])

    def approve_po(self, po_id, *, actor, revision):
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] != 'draft' or order['revision'] != revision:
                raise ValidationError('This order changed or is already approved. Refresh the order.')
            budget_row=db.execute("SELECT value FROM settings WHERE key='monthly_budget'").fetchone()
            budget=scaled(budget_row['value'],'Monthly budget',100) if budget_row else 0
            if budget:
                month=datetime.now().strftime('%Y-%m')
                committed=sum(line_value(r['qty'],r['price']) for r in db.execute("""SELECT CASE WHEN o.state='cancelled' THEN l.received ELSE l.qty END qty,l.price FROM po_lines l JOIN purchase_orders o ON o.id=l.po_id
                    WHERE o.id<>? AND substr(o.approved_at,1,7)=? AND o.state IN ('approved','sending','sent','partial','received','delivery_unknown','cancelled')""",(po_id,month)))
                if committed+order['total']>budget:
                    raise ValidationError('This approval exceeds the monthly purchase budget. Ask an owner to review the budget in Settings.')
            subject, body = self.draft_email(order)
            db.execute("UPDATE purchase_orders SET state='approved',subject=?,body=?,approval_hash=?,approved_at=? WHERE id=?",
                       (subject, body, self._approval(order, subject, body), now(), po_id))
            self._audit(db, actor, 'po_approved', order['number'], {'revision': revision, 'total_paise': order['total']})

    def _check_approval(self, order):
        if not order['approval_hash'] or order['approval_hash'] != self._approval(order, order['subject'], order['body']):
            raise ValidationError('Approved order content has changed. Create a new approval before sending.')

    def place_manually(self, po_id, reference, *, actor, revision):
        reference = text(reference, 'Supplier confirmation or order reference', required=True, limit=500)
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] != 'approved' or order['revision'] != revision:
                raise ValidationError('Only the current approved order can be marked as placed.')
            self._check_approval(order)
            db.execute("UPDATE purchase_orders SET state='sent',sent_at=? WHERE id=?", (now(), po_id))
            self._audit(db, actor, 'po_placed_manually', order['number'], {'reference': reference})

    def send_po(self, po_id, *, actor, dry_run=True, sender=None):
        from tools import send_email
        sender = sender or send_email
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] not in ('draft', 'approved'):
                raise ValidationError('This order has already been placed or requires delivery reconciliation.')
            if dry_run:
                subject, body = (order['subject'], order['body']) if order['state'] == 'approved' else self.draft_email(order)
                return {'status': 'ok', 'mode': 'dry_run', 'to': order['supplier_email'], 'subject': subject, 'body': body}
            if order['state'] != 'approved':
                raise ValidationError('Approve this order before sending it.')
            self._check_approval(order)
            email(order['supplier_email'], required=True)
            attempt = db.execute("INSERT INTO deliveries(po_id,revision,state,created_at) VALUES(?,?,'sending',?)",
                                 (po_id, order['revision'], now())).lastrowid
            db.execute("UPDATE purchase_orders SET state='sending',last_error='' WHERE id=?", (po_id,))
            self._audit(db, actor, 'email_attempt_started', order['number'], {'attempt': attempt})
        # Persist the attempt BEFORE contacting SMTP. Never retry an uncertain delivery automatically.
        try:
            result = sender(order['supplier_email'], order['subject'], order['body'], dry_run=False)
            result = json.loads(result) if isinstance(result, str) else result
            if not isinstance(result, dict):
                raise ValueError('Invalid email transport response.')
        except Exception as exc:
            result = {'status': 'error', 'delivery': 'unknown', 'message': str(exc)}
        success = result.get('status') == 'ok' and result.get('mode') != 'dry_run'
        state = 'sent' if success else ('approved' if result.get('delivery') == 'not_sent' else 'delivery_unknown')
        detail = str(result.get('message', ''))[:2000]
        with self.connect(True) as db:
            current = self._order(db, po_id)
            if current['state'] != 'sending':
                raise ValidationError('Delivery status changed while sending. Review the order history.')
            db.execute('UPDATE purchase_orders SET state=?,sent_at=?,last_error=? WHERE id=?',
                       (state, now() if success else None, detail, po_id))
            db.execute('UPDATE deliveries SET state=?,detail=?,finished_at=? WHERE id=?', (state, detail, now(), attempt))
            self._audit(db, actor, 'email_attempt_finished', order['number'], {'state': state, 'attempt': attempt})
        return result

    def reconcile_delivery(self, po_id, delivered, evidence, *, actor):
        evidence = text(evidence, 'Reconciliation evidence', required=True, limit=1000)
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] not in ('delivery_unknown', 'sending'):
                raise ValidationError('Only an uncertain delivery can be reconciled.')
            # A running attempt is only recoverable after its SMTP timeout budget has elapsed.
            attempt = db.execute('SELECT * FROM deliveries WHERE po_id=? ORDER BY id DESC LIMIT 1', (po_id,)).fetchone()
            if order['state'] == 'sending' and attempt:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(attempt['created_at'])).total_seconds()
                if age < 300:
                    raise ValidationError('This send may still be in progress. Wait five minutes before reconciling.')
            state = 'sent' if delivered else 'approved'
            db.execute('UPDATE purchase_orders SET state=?,sent_at=?,last_error=? WHERE id=?', (state, now() if delivered else None, evidence, po_id))
            if attempt:
                db.execute('UPDATE deliveries SET state=?,detail=?,finished_at=? WHERE id=?', (state, evidence, now(), attempt['id']))
            self._audit(db, actor, 'delivery_reconciled', order['number'], {'delivered': bool(delivered), 'evidence': evidence})

    def cancel_po(self, po_id, reason, *, actor):
        reason = text(reason, 'Cancellation reason', required=True, limit=500)
        with self.connect(True) as db:
            order = self._order(db, po_id)
            if order['state'] not in ('draft', 'approved', 'sent', 'partial'):
                raise ValidationError('This order cannot be cancelled in its current state.')
            db.execute("UPDATE purchase_orders SET state='cancelled' WHERE id=?", (po_id,))
            self._audit(db, actor, 'po_cancelled', order['number'], {'reason': reason, 'previous_state': order['state']})

    def receive_po(self, po_id, received, *, actor, token, reference, location_id=1, batches=None, freight='0', quality_hold=False):
        reference = text(reference, 'Delivery reference', required=True, limit=200)
        received = {int(k): scaled(v, 'Received quantity') for k, v in received.items()}
        if not received or not any(received.values()):
            raise ValidationError('Enter at least one quantity received.')
        batches = {int(k):v for k,v in (batches or {}).items()}
        freight = scaled(freight,'Receipt freight / overhead',100)
        payload = ['receive', po_id, received, reference, actor_name(actor),location_id,batches,freight]
        if quality_hold:payload.append('quality_hold')
        with self.connect(True) as db:
            previous = self._once(db, token, payload)
            if previous is not None:
                return previous
            order = self._order(db, po_id)
            if order['state'] not in ('sent', 'partial'):
                raise ValidationError('Only a placed order can receive goods.')
            lines = {l['id']: l for l in order['lines']}
            if set(received) - set(lines):
                raise ValidationError('Receipt contains a line from another purchase order.')
            total_value = sum(line_value(q,lines[lid]['price']) for lid,q in received.items())
            if freight and not total_value:
                raise ValidationError('Freight allocation needs a non-zero goods value.')
            allocation_remaining = freight
            positive_lines = [lid for lid,q in received.items() if q]
            for line_id, qty in received.items():
                line = lines[line_id]
                if qty > line['qty'] - line['received']:
                    raise ValidationError(f'Receipt exceeds the outstanding quantity for {line["item_code"]}.')
                if qty:
                    share = allocation_remaining if line_id==positive_lines[-1] else min(allocation_remaining,rounded(freight*line_value(qty,line['price']),total_value)) if total_value else 0
                    allocation_remaining -= share
                    self._movement(db, line['product_id'], qty, 'po_receipt', 'Purchase order receipt', f'{order["number"]} / {reference}', actor,
                        location_id,batches.get(line_id),total_cost=line_value(qty,line['price'])+share)
                    if quality_hold:
                        self._open_inspection(db,line['product_id'],location_id,batches.get(line_id),qty,'incoming',f'{order["number"]} / {reference}',actor)
                    db.execute('UPDATE po_lines SET received=received+? WHERE id=?', (qty, line_id))
            remains = db.execute('SELECT SUM(qty-received) FROM po_lines WHERE po_id=?', (po_id,)).fetchone()[0]
            state = 'partial' if remains else 'received'
            db.execute('UPDATE purchase_orders SET state=? WHERE id=?', (state, po_id))
            self._audit(db, actor, 'goods_received', order['number'], {'reference': reference, 'quantities': received})
            return self._done(db, token, payload, state)

    def backup(self):
        with tempfile.TemporaryDirectory(prefix='stocklist-backup-') as folder:
            path = Path(folder) / 'stocklist.sqlite3'
            with self.connect() as source:
                dest = sqlite3.connect(path)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
            return path.read_bytes()

    def health(self):
        with self.connect() as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            fk = db.execute('PRAGMA foreign_key_check').fetchall()
            ledger_errors=db.execute('''SELECT COUNT(*) FROM (SELECT m.product_id,m.location_id,SUM(m.delta) qty,v.qty recorded
                FROM movements m LEFT JOIN valuations v ON v.product_id=m.product_id AND v.location_id=m.location_id
                GROUP BY m.product_id,m.location_id HAVING v.qty IS NULL OR SUM(m.delta)<>v.qty)''').fetchone()[0]
            return {'integrity': integrity, 'foreign_key_errors': len(fk), 'ledger_balance_errors':ledger_errors,'schema_version': VERSION}
