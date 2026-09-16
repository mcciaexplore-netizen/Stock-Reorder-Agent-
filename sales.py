"""Customer invoices, tax breakdowns, stock dispatch and linked credit notes."""
from datetime import date, datetime, timezone
import html
import json
import re

from inventory import ValidationError, amount, line_value, quantity, scaled, text
from inventory_ops import day, rounded


def gstin(value):
    value=text(value,'GSTIN',limit=15).upper()
    if value and not re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]',value):
        raise ValidationError('GSTIN must have the expected 15-character format.')
    return value


def state_code(value, required=False):
    value=text(value,'State / territory code',required=required,limit=2)
    if value and (not value.isdigit() or not 1<=int(value)<=38):raise ValidationError('Enter a two-digit Indian state / territory code (01–38).')
    return value.zfill(2) if value else ''


class Sales:
    def customers(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM customers ORDER BY name')]

    def save_customer(self,name,address='',gst_number='',state='',phone='',*,actor,customer_id=None):
        name=text(name,'Customer',required=True,limit=200); address=text(address,'Address',limit=1000)
        gst_number=gstin(gst_number); state=state_code(state); phone=text(phone,'Phone',limit=60)
        if gst_number and gst_number[:2]!=state:raise ValidationError('Customer state code must match the GSTIN prefix.')
        with self.connect(True) as db:
            if customer_id:
                changed=db.execute('UPDATE customers SET name=?,address=?,gstin=?,state_code=?,phone=? WHERE id=?',(name,address,gst_number,state,phone,customer_id)).rowcount
                if not changed:raise ValidationError('Customer no longer exists.')
            else:
                customer_id=db.execute('INSERT INTO customers(name,address,gstin,state_code,phone) VALUES(?,?,?,?,?)',(name,address,gst_number,state,phone)).lastrowid
            self._audit(db,actor,'customer_saved',customer_id,{'name':name})
            return customer_id

    def _invoice_snapshot(self,db,customer_id,place_of_supply):
        customer=db.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone()
        if not customer:raise ValidationError('Choose a customer.')
        business={r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
        if not business.get('business_name') or not business.get('business_address'):
            raise ValidationError('Set the business name and address in Settings before invoicing.')
        supply=state_code(place_of_supply or customer['state_code'],required=bool(business.get('gstin')))
        return {'customer':dict(customer),'business':{k:business.get(k,'') for k in ('business_name','business_address','gstin','state_code')},'place_of_supply':supply}

    def issue_invoice(self,customer_id,lines,location_id,invoice_date,due_date,place_of_supply='',*,actor,token,dispatch_id=None):
        invoice_date=day(invoice_date); due_date=day(due_date)
        if due_date<invoice_date:raise ValidationError('Payment due date cannot precede invoice date.')
        payload=['invoice',customer_id,lines,location_id,invoice_date,due_date,place_of_supply]
        if dispatch_id is not None:payload.append(dispatch_id)
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            if dispatch_id is not None:
                dispatch=db.execute('SELECT d.*,o.customer_id FROM sales_dispatches d JOIN sales_orders o ON o.id=d.order_id WHERE d.id=?',(dispatch_id,)).fetchone()
                if not dispatch or dispatch['invoice_id'] is not None:
                    raise ValidationError('This delivery note is missing or already invoiced.')
                if customer_id!=dispatch['customer_id'] or location_id!=dispatch['location_id'] or invoice_date<dispatch['dispatch_date']:
                    raise ValidationError('Invoice customer and location must match the delivery, and the invoice date cannot precede dispatch.')
                expected={(r['product_id'],r['batch_id']):(r['qty'],r['price'],r['tax_rate']) for r in self._dispatch_invoice_lines(db,dispatch_id)}
                actual={(r['product_id'],r.get('batch_id')):(scaled(r['qty']),scaled(r['price'],'Price',100),scaled(r['tax_rate'],'Tax rate',100)) for r in lines}
                if actual!=expected or len(lines)!=len(expected):
                    raise ValidationError('Use the quantities and prices from this delivery note.')
            snapshot=self._invoice_snapshot(db,customer_id,place_of_supply)
            business=snapshot['business']; intra=business['state_code']==snapshot['place_of_supply']
            if not lines:raise ValidationError('Add at least one invoice line.')
            values=[]; subtotal=cgst=sgst=igst=0
            seen=set()
            for raw in lines:
                p=self._product(db,raw['product_id']); batch_id=raw.get('batch_id')
                key=(p['id'],batch_id)
                if key in seen:raise ValidationError('Combine duplicate product and batch lines.')
                seen.add(key)
                qty=scaled(raw['qty']); price=scaled(raw['price'],'Selling price',100)
                rate=scaled(raw.get('tax_rate',amount(p['tax_rate'])),'Tax rate',100)
                if qty<=0 or rate>10000:raise ValidationError('Quantity must be positive and tax between 0 and 100%.')
                if rate and (not business['gstin'] or not business['state_code'] or not p['hsn']):
                    raise ValidationError('Taxable invoices require business GSTIN, state code and a product HSN.')
                if business['gstin'] and not snapshot['customer']['address']:
                    raise ValidationError('Record the customer address before issuing a tax invoice.')
                net=line_value(qty,price)
                central=rounded(net*rate,20000) if intra else 0
                state_tax=central if intra else 0
                integrated=rounded(net*rate,10000) if not intra else 0
                if intra:
                    cgst+=central; sgst+=state_tax
                else:igst+=integrated
                subtotal+=net
                values.append((p,qty,price,rate,batch_id,net,central,state_tax,integrated))
            iid=db.execute('INSERT INTO invoices(customer_id,kind,invoice_date,due_date,location_id,snapshot,subtotal,cgst,sgst,igst,total,created_at,actor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (customer_id,'invoice',invoice_date,due_date,location_id,json.dumps(snapshot),subtotal,cgst,sgst,igst,subtotal+cgst+sgst+igst,datetime.now(timezone.utc).isoformat(),actor)).lastrowid
            year=int(invoice_date[:4])-(int(invoice_date[5:7])<4)
            number=f'INV/{year%100:02d}/{iid:07d}'
            db.execute('UPDATE invoices SET number=? WHERE id=?',(number,iid))
            for p,qty,price,rate,batch_id,net,ctax,stax,itax in values:
                if dispatch_id is None:
                    mids=self._take(db,p['id'],qty,location_id,'invoice_sale','Invoice dispatch',number,actor,batch_id)
                else:
                    mids=[r[0] for r in db.execute('''SELECT m.id FROM sales_dispatch_lines d JOIN movements m ON m.id=d.movement_id
                        WHERE d.dispatch_id=? AND m.product_id=? AND m.batch_id IS ? ORDER BY m.id''',(dispatch_id,p['id'],batch_id))]
                # Keep allocation lines for traceable credit returns, including automatic FEFO selections.
                consumed=0
                for mid in mids:
                    m=db.execute('SELECT * FROM movements WHERE id=?',(mid,)).fetchone()
                    split=[rounded(v*(consumed-m['delta']),qty)-rounded(v*consumed,qty) for v in (net,ctax,stax,itax)]
                    consumed-=m['delta']
                    db.execute('INSERT INTO invoice_lines(invoice_id,product_id,qty,price,tax_rate,hsn,description,unit,cost,net,cgst,sgst,igst,batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (iid,p['id'],-m['delta'],price,rate,p['hsn'],p['item_name'],p['unit'],-m['value_delta'],*split,m['batch_id']))
            if dispatch_id is not None:
                db.execute('UPDATE sales_dispatches SET invoice_id=? WHERE id=?',(iid,dispatch_id))
            self._audit(db,actor,'invoice_issued',iid,{'number':number,'total':subtotal+cgst+sgst+igst,'delivery_note':dispatch_id})
            return self._done(db,token,payload,iid)

    def invoices(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT i.*,c.name customer,
                COALESCE((SELECT SUM(amount) FROM payments p WHERE p.invoice_id=i.id),0) paid,
                COALESCE((SELECT SUM(total) FROM invoices credit WHERE credit.original_id=i.id),0) credited
                FROM invoices i JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC''')]

    def invoice(self,invoice_id):
        with self.connect() as db:
            r=db.execute('SELECT * FROM invoices WHERE id=?',(invoice_id,)).fetchone()
            if not r:raise ValidationError('Invoice no longer exists.')
            result=dict(r); result['snapshot']=json.loads(result['snapshot'])
            result['lines']=[dict(r) for r in db.execute('''SELECT l.*,p.item_code,
                COALESCE((SELECT SUM(qty) FROM invoice_lines c WHERE c.original_line_id=l.id),0) returned
                FROM invoice_lines l JOIN products p ON p.id=l.product_id WHERE l.invoice_id=?''',(invoice_id,))]
            return result

    def credit_invoice(self,invoice_id,returns,reason,*,actor,token):
        reason=text(reason,'Return reason',required=True,limit=500)
        returns={int(k):scaled(v,'Return quantity') for k,v in returns.items()}
        payload=['credit',invoice_id,returns,reason]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            original=db.execute("SELECT * FROM invoices WHERE id=? AND kind='invoice'",(invoice_id,)).fetchone()
            if not original:raise ValidationError('Choose an original sales invoice.')
            if not any(returns.values()):raise ValidationError('Enter a quantity to return.')
            snapshot=json.loads(original['snapshot']); snapshot['return_reason']=reason; snapshot['original_number']=original['number']; snapshot['original_date']=original['invoice_date']
            intra=snapshot['business']['state_code']==snapshot['place_of_supply']
            subtotal=cgst=sgst=igst=0; checked=[]
            for lid,qty in returns.items():
                l=db.execute('SELECT * FROM invoice_lines WHERE id=? AND invoice_id=?',(lid,invoice_id)).fetchone()
                if not l:raise ValidationError('Return line does not belong to the selected invoice.')
                previous=db.execute('SELECT COALESCE(SUM(qty),0) FROM invoice_lines WHERE original_line_id=?',(lid,)).fetchone()[0]
                if qty>l['qty']-previous:raise ValidationError('Return exceeds the quantity sold and not already returned.')
                if not qty:continue
                parts=[rounded(l[field]*(previous+qty),l['qty'])-rounded(l[field]*previous,l['qty']) for field in ('net','cgst','sgst','igst','cost')]
                subtotal+=parts[0]; cgst+=parts[1]; sgst+=parts[2]; igst+=parts[3]
                checked.append((l,qty,parts))
            total=subtotal+cgst+sgst+igst
            credited=db.execute('SELECT COALESCE(SUM(total),0) FROM invoices WHERE original_id=?',(invoice_id,)).fetchone()[0]
            if total+credited>original['total']:
                raise ValidationError('Credit exceeds the original invoice total; consolidate return quantities to avoid rounding differences.')
            today=date.today().isoformat()
            cid=db.execute('INSERT INTO invoices(customer_id,kind,original_id,invoice_date,due_date,location_id,snapshot,subtotal,cgst,sgst,igst,total,created_at,actor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (original['customer_id'],'credit',invoice_id,today,today,original['location_id'],json.dumps(snapshot),subtotal,cgst,sgst,igst,total,datetime.now(timezone.utc).isoformat(),actor)).lastrowid
            number=f'CR/{date.today().year%100:02d}/{cid:07d}'
            db.execute('UPDATE invoices SET number=? WHERE id=?',(number,cid))
            for l,qty,parts in checked:
                cost=parts[4]
                self._movement(db,l['product_id'],qty,'invoice_return',reason,number,actor,location_id=original['location_id'],batch_id=l['batch_id'],total_cost=cost)
                db.execute('INSERT INTO invoice_lines(invoice_id,product_id,qty,price,tax_rate,hsn,description,unit,cost,net,cgst,sgst,igst,original_line_id,batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (cid,l['product_id'],qty,l['price'],l['tax_rate'],l['hsn'],l['description'],l['unit'],cost,*parts[:4],l['id'],l['batch_id']))
            self._audit(db,actor,'credit_note_issued',cid,{'original':invoice_id,'reason':reason})
            return self._done(db,token,payload,cid)

    def record_payment(self,invoice_id,value,reference,*,actor,token):
        value=scaled(value,'Payment',100); reference=text(reference,'Payment reference',required=True,limit=200)
        payload=['payment',invoice_id,value,reference]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            invoice=db.execute("SELECT * FROM invoices WHERE id=? AND kind='invoice'",(invoice_id,)).fetchone()
            if not invoice or value<=0:raise ValidationError('Choose a sales invoice and a positive amount.')
            paid=db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=?',(invoice_id,)).fetchone()[0]
            credited=db.execute('SELECT COALESCE(SUM(total),0) FROM invoices WHERE original_id=?',(invoice_id,)).fetchone()[0]
            if value>invoice['total']-paid-credited:raise ValidationError('Payment exceeds the remaining amount due.')
            pid=db.execute("INSERT INTO payments(invoice_id,amount,reference,created_at) VALUES(?,?,?,datetime('now'))",(invoice_id,value,reference)).lastrowid
            self._audit(db,actor,'payment_recorded',invoice_id,{'paise':value,'reference':reference})
            return self._done(db,token,payload,pid)

    def invoice_document(self,invoice_id):
        inv=self.invoice(invoice_id); snap=inv['snapshot']; esc=lambda x:html.escape(str(x))
        business=snap['business']; customer=snap['customer']
        rows=''.join(f'<tr><td>{esc(l["description"])}</td><td>{esc(l["hsn"])}</td><td>{quantity(l["qty"])}</td><td>{esc(l["unit"])}</td><td>{amount(l["price"])}</td><td>{amount(l["tax_rate"])}%</td><td>{amount(l["net"])}</td></tr>' for l in inv['lines'])
        title='Credit note' if inv['kind']=='credit' else ('Tax invoice' if business['gstin'] else 'Invoice')
        original=f'<p>Against {esc(snap["original_number"])} dated {esc(snap["original_date"])}</p>' if inv['kind']=='credit' else ''
        return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{esc(inv['number'])}</title>
        <style>body{{font:15px system-ui;margin:40px;color:#182c28}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:10px;text-align:left}}.totals{{text-align:right}}@media print{{body{{margin:12mm}}}}</style>
        <h1>{title} · {esc(inv['number'])}</h1><h2>{esc(business['business_name'])}</h2><p>{esc(business['business_address'])}<br>GSTIN: {esc(business['gstin'] or 'Unregistered')}</p>
        <p>Date: {inv['invoice_date']} · Due: {inv['due_date']}</p>{original}<h3>Bill to: {esc(customer['name'])}</h3><p>{esc(customer['address'])}<br>GSTIN: {esc(customer['gstin'] or 'Unregistered')}<br>Place of supply: {esc(snap['place_of_supply'])}</p>
        <table><thead><tr><th>Item</th><th>HSN</th><th>Quantity</th><th>Unit</th><th>Price ₹</th><th>GST</th><th>Taxable ₹</th></tr></thead><tbody>{rows}</tbody></table>
        <div class="totals"><p>Taxable value: ₹{amount(inv['subtotal'])}</p><p>CGST: ₹{amount(inv['cgst'])} · SGST/UTGST: ₹{amount(inv['sgst'])} · IGST: ₹{amount(inv['igst'])}</p><h2>Total: ₹{amount(inv['total'])}</h2></div>
        <p>Reverse charge: No</p><p>Authorised signatory: ____________________</p></html>'''.encode('utf-8')
