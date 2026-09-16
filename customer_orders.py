"""Customer commitments, partial delivery notes and invoicing without a second stock issue."""
from datetime import date
import html
import json

from inventory import ValidationError, amount, quantity, scaled, text, line_value
from inventory_ops import day


class CustomerOrders:
    def customer_quotes(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT q.*,c.name customer FROM customer_quotes q JOIN customers c ON c.id=q.customer_id ORDER BY q.id DESC')]

    def create_customer_quote(self, customer_id, lines, valid_until, delivery_date, notes='', *, actor, token):
        valid_until=day(valid_until); delivery_date=day(delivery_date)
        notes=text(notes,'Terms and notes',limit=2000)
        if valid_until<date.today().isoformat():
            raise ValidationError('A new quotation cannot already be expired.')
        payload=['customer_quote',customer_id,lines,valid_until,delivery_date,notes]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            c=db.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone()
            if not c or not lines:raise ValidationError('Choose a customer and at least one product.')
            snapshot={'customer':dict(c),'products':{}}
            checked=[]; seen=set()
            for raw in lines:
                p=self._product(db,raw['product_id'])
                qty=scaled(raw['qty']); price=scaled(raw['price'],'Price',100)
                tax=scaled(raw.get('tax_rate',amount(p['tax_rate'])),'Tax rate',100)
                if qty<=0 or tax>10000 or p['id'] in seen:
                    raise ValidationError('Use positive quantities, tax from 0 to 100%, and one line per product.')
                line_value(qty,price)
                seen.add(p['id']); snapshot['products'][str(p['id'])]=p
                checked.append((p['id'],qty,price,tax))
            qid=db.execute("INSERT INTO customer_quotes(customer_id,valid_until,delivery_date,notes,snapshot,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                (customer_id,valid_until,delivery_date,notes,json.dumps(snapshot))).lastrowid
            db.execute('UPDATE customer_quotes SET number=? WHERE id=?',(f'CQ-{qid:06d}',qid))
            db.executemany('INSERT INTO customer_quote_lines(quote_id,product_id,qty,price,tax_rate) VALUES(?,?,?,?,?)',[(qid,*r) for r in checked])
            self._audit(db,actor,'customer_quote_created',qid,{'customer':customer_id})
            return self._done(db,token,payload,qid)

    def confirm_customer_quote(self, quote_id, *, actor, token):
        payload=['confirm_customer_quote',quote_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            q=db.execute("SELECT * FROM customer_quotes WHERE id=? AND state='open'",(quote_id,)).fetchone()
            if not q:raise ValidationError('This quotation has already been confirmed or cancelled.')
            if q['valid_until']<date.today().isoformat():raise ValidationError('This quotation has expired. Create a new quotation.')
            oid=db.execute("INSERT INTO sales_orders(quote_id,customer_id,delivery_date,notes,snapshot,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                (quote_id,q['customer_id'],q['delivery_date'],q['notes'],q['snapshot'])).lastrowid
            db.execute('UPDATE sales_orders SET number=? WHERE id=?',(f'SO-{oid:06d}',oid))
            db.execute('INSERT INTO sales_order_lines(order_id,product_id,qty,price,tax_rate) SELECT ?,product_id,qty,price,tax_rate FROM customer_quote_lines WHERE quote_id=?',(oid,quote_id))
            db.execute("UPDATE customer_quotes SET state='converted' WHERE id=?",(quote_id,))
            self._audit(db,actor,'sales_order_confirmed',oid,{'quote':quote_id})
            return self._done(db,token,payload,oid)

    def cancel_customer_quote(self, quote_id, *, actor):
        with self.connect(True) as db:
            if not db.execute("UPDATE customer_quotes SET state='cancelled' WHERE id=? AND state='open'",(quote_id,)).rowcount:
                raise ValidationError('Only an open quotation can be cancelled.')
            self._audit(db,actor,'customer_quote_cancelled',quote_id,{})

    def sales_orders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT o.*,c.name customer,
                (SELECT SUM(qty-dispatched) FROM sales_order_lines WHERE order_id=o.id) pending
                FROM sales_orders o JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC''')]

    def sales_order(self, order_id):
        with self.connect() as db:
            o=db.execute('SELECT * FROM sales_orders WHERE id=?',(order_id,)).fetchone()
            if not o:raise ValidationError('Sales order no longer exists.')
            return dict(o,lines=[dict(r) for r in db.execute('''SELECT l.*,p.item_name,p.item_code,p.unit FROM sales_order_lines l
                JOIN products p ON p.id=l.product_id WHERE l.order_id=?''',(order_id,))])

    def set_sales_commitment(self, order_id, delivery_date, reason, *, actor):
        due=day(delivery_date); reason=text(reason,'Reason',required=True,limit=500)
        with self.connect(True) as db:
            o=db.execute("SELECT * FROM sales_orders WHERE id=? AND state IN ('confirmed','partial')",(order_id,)).fetchone()
            if not o:raise ValidationError('Only an open order can be rescheduled.')
            db.execute('UPDATE sales_orders SET delivery_date=? WHERE id=?',(due,order_id))
            self._audit(db,actor,'delivery_commitment_changed',order_id,{'previous':o['delivery_date'],'new':due,'reason':reason})

    def cancel_sales_order(self, order_id, reason, *, actor):
        reason=text(reason,'Cancellation reason',required=True,limit=500)
        with self.connect(True) as db:
            o=db.execute("SELECT * FROM sales_orders WHERE id=? AND state IN ('confirmed','partial')",(order_id,)).fetchone()
            if not o:raise ValidationError('Only an open order can be cancelled.')
            if db.execute("SELECT 1 FROM work_orders w JOIN sales_order_lines l ON l.id=w.order_line_id WHERE l.order_id=? AND w.state NOT IN ('completed','cancelled')",(order_id,)).fetchone():
                raise ValidationError('Complete or cancel linked work orders before cancelling this commitment.')
            db.execute("UPDATE sales_orders SET state='cancelled' WHERE id=?",(order_id,))
            self._audit(db,actor,'sales_order_balance_cancelled',order_id,{'reason':reason})

    def dispatch_sales_order(self, order_id, quantities, location_id, reference, dispatch_date, *, actor, token):
        quantities={int(k):scaled(v) for k,v in quantities.items()}
        reference=text(reference,'Delivery reference',required=True,limit=200); dispatch_date=day(dispatch_date)
        if dispatch_date>date.today().isoformat():raise ValidationError('Record dispatch on or before today; use the order for future commitments.')
        payload=['sales_dispatch',order_id,quantities,location_id,reference,dispatch_date]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            order=db.execute("SELECT * FROM sales_orders WHERE id=? AND state IN ('confirmed','partial')",(order_id,)).fetchone()
            if not order or not any(quantities.values()):raise ValidationError('Choose an open order and a positive delivery quantity.')
            self._location(db,location_id)
            did=db.execute("INSERT INTO sales_dispatches(order_id,location_id,reference,dispatch_date,created_at) VALUES(?,?,?,?,datetime('now'))",(order_id,location_id,reference,dispatch_date)).lastrowid
            number=f'DN-{did:06d}'; db.execute('UPDATE sales_dispatches SET number=? WHERE id=?',(number,did))
            for lid,qty in quantities.items():
                l=db.execute('SELECT * FROM sales_order_lines WHERE id=? AND order_id=?',(lid,order_id)).fetchone()
                if not l or qty>l['qty']-l['dispatched']:raise ValidationError('Dispatch exceeds the pending order quantity or uses another order line.')
                if not qty:continue
                mids=self._take(db,l['product_id'],qty,location_id,'order_dispatch','Customer order delivery',number,actor)
                db.executemany('INSERT INTO sales_dispatch_lines(dispatch_id,order_line_id,movement_id) VALUES(?,?,?)',[(did,lid,m) for m in mids])
                db.execute('UPDATE sales_order_lines SET dispatched=dispatched+? WHERE id=?',(qty,lid))
            pending=db.execute('SELECT SUM(qty-dispatched) FROM sales_order_lines WHERE order_id=?',(order_id,)).fetchone()[0]
            db.execute('UPDATE sales_orders SET state=? WHERE id=?',('partial' if pending else 'fulfilled',order_id))
            self._audit(db,actor,'sales_order_dispatched',did,{'order':order_id,'quantities':quantities})
            return self._done(db,token,payload,did)

    def sales_dispatches(self, order_id=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT d.*,o.number order_number,c.name customer FROM sales_dispatches d
                JOIN sales_orders o ON o.id=d.order_id JOIN customers c ON c.id=o.customer_id '''+
                ('WHERE d.order_id=? ' if order_id else '')+'ORDER BY d.id DESC',(order_id,) if order_id else ())]

    def _dispatch_invoice_lines(self, db, dispatch_id):
        return [dict(r) for r in db.execute('''SELECT l.product_id,l.price,l.tax_rate,m.batch_id,-SUM(m.delta) qty
            FROM sales_dispatch_lines d JOIN sales_order_lines l ON l.id=d.order_line_id
            JOIN movements m ON m.id=d.movement_id WHERE d.dispatch_id=? GROUP BY l.id,m.batch_id''',(dispatch_id,))]

    def invoice_sales_dispatch(self, dispatch_id, invoice_date, due_date, *, actor, token):
        with self.connect() as db:
            d=db.execute('SELECT d.*,o.customer_id FROM sales_dispatches d JOIN sales_orders o ON o.id=d.order_id WHERE d.id=?',(dispatch_id,)).fetchone()
            if not d:raise ValidationError('Choose a delivery note.')
            lines=[dict(l,qty=quantity(l['qty']),price=amount(l['price']),tax_rate=amount(l['tax_rate'])) for l in self._dispatch_invoice_lines(db,dispatch_id)]
        return self.issue_invoice(d['customer_id'],lines,d['location_id'],invoice_date,due_date,
            actor=actor,token=token,dispatch_id=dispatch_id)

    def customer_document(self, kind, record_id):
        if kind not in ('quote','order','delivery'):raise ValidationError('Choose quotation, order or delivery.')
        with self.connect() as db:
            if kind=='quote':
                doc=db.execute('SELECT * FROM customer_quotes WHERE id=?',(record_id,)).fetchone()
                lines=db.execute('SELECT product_id,qty,price FROM customer_quote_lines WHERE quote_id=?',(record_id,)).fetchall()
            elif kind=='order':
                doc=db.execute('SELECT * FROM sales_orders WHERE id=?',(record_id,)).fetchone()
                lines=db.execute('SELECT product_id,qty,price FROM sales_order_lines WHERE order_id=?',(record_id,)).fetchall()
            else:
                doc=db.execute('''SELECT d.number,d.reference notes,d.dispatch_date delivery_date,o.snapshot FROM sales_dispatches d
                    JOIN sales_orders o ON o.id=d.order_id WHERE d.id=?''',(record_id,)).fetchone()
                lines=self._dispatch_invoice_lines(db,record_id)
            if not doc:raise ValidationError('Document no longer exists.')
            snap=json.loads(doc['snapshot']); esc=lambda v:html.escape(str(v))
            rows=''.join(f'<tr><td>{esc(snap["products"][str(l["product_id"])]["item_name"])}</td><td>{quantity(l["qty"])}</td><td>{esc(snap["products"][str(l["product_id"])]["unit"])}</td><td>{amount(l["price"])}</td><td>{amount(line_value(l["qty"],l["price"]))}</td></tr>' for l in lines)
            title={'quote':'Customer quotation','order':'Confirmed sales order','delivery':'Delivery note'}[kind]
            validity=f'<p>Valid until {esc(doc["valid_until"])}</p>' if kind=='quote' else ''
            return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{esc(doc['number'])}</title>
                <style>body{{font:16px system-ui;margin:40px;color:#203b50}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}</style>
                <h1>{title} · {esc(doc['number'])}</h1><h2>{esc(snap['customer']['name'])}</h2>
                <p>Delivery date: {esc(doc['delivery_date'])}</p>{validity}<p>{esc(doc['notes'])}</p>
                <table><tr><th>Product</th><th>Quantity</th><th>Unit</th><th>Unit price ₹</th><th>Net value ₹</th></tr>{rows}</table>
                <p>Values exclude tax. This document is not a tax invoice.</p></html>'''.encode('utf-8')
