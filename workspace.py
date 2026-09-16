"""Business settings, operating reports, exceptions and local maintenance."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from inventory import ValidationError, amount, csv_bytes, quantity, scaled, text
from inventory_ops import day
from sales import gstin, state_code


class Workspace:
    def settings(self):
        with self.connect() as db:
            return {r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}

    def save_settings(self,values,*,actor):
        allowed={'business_name','business_address','gstin','state_code','monthly_budget','backup_enabled','backup_days','default_industry','language'}
        if set(values)-allowed:raise ValidationError('Unsupported business setting.')
        clean={k:text(v,k,limit=1000) for k,v in values.items()}
        if 'gstin' in clean:clean['gstin']=gstin(clean['gstin'])
        if 'state_code' in clean:clean['state_code']=state_code(clean['state_code'])
        if clean.get('gstin') and clean['gstin'][:2]!=clean.get('state_code'):
            raise ValidationError('Business state must match its GSTIN prefix.')
        if 'monthly_budget' in clean:scaled(clean['monthly_budget'],'Monthly purchase budget',100)
        if 'backup_days' in clean:
            days=scaled(clean['backup_days'],'Backup interval',1)
            if not 1<=days<=30:raise ValidationError('Backup interval must be 1–30 days.')
        if clean.get('backup_enabled','false') not in ('true','false'):raise ValidationError('Invalid backup setting.')
        if clean.get('language','English') not in ('English','Hindi'):raise ValidationError('Choose English or Hindi navigation.')
        with self.connect(True) as db:
            for k,v in clean.items():db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
            self._audit(db,actor,'business_settings_saved','business',clean)

    def reports(self):
        cutoff=(date.today()-timedelta(days=30)).isoformat()
        with self.connect() as db:
            stock=[dict(r) for r in db.execute('''SELECT p.item_code,p.item_name,p.unit,l.name location,v.qty,v.value,
                COALESCE((SELECT -SUM(delta) FROM movements m WHERE m.product_id=p.id AND m.location_id=l.id
                AND m.kind IN ('sale','invoice_sale','issue','job_issue','production_issue','order_dispatch','work_consumption','jobwork_consume') AND m.created_at>=?),0) used_30_days,
                (SELECT MAX(created_at) FROM movements m WHERE m.product_id=p.id AND m.location_id=l.id AND delta<0) last_outgoing
                FROM valuations v JOIN products p ON p.id=v.product_id JOIN locations l ON l.id=v.location_id ORDER BY p.item_name''',(cutoff,))]
            margins=[dict(r) for r in db.execute('''SELECT i.number,i.invoice_date,c.name customer,i.kind,i.subtotal,
                COALESCE((SELECT SUM(cost) FROM invoice_lines l WHERE l.invoice_id=i.id),0) cost
                FROM invoices i JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC''')]
            suppliers=[dict(r) for r in db.execute('''SELECT s.name,s.id,
                (SELECT COUNT(*) FROM purchase_orders o WHERE o.supplier_id=s.id AND o.state IN ('sent','partial','received')) orders,
                (SELECT COUNT(*) FROM purchase_orders o WHERE o.supplier_id=s.id AND o.state IN ('sent','partial') AND o.due_date<>'' AND o.due_date<?) overdue,
                (SELECT AVG(julianday(m.created_at)-julianday(o.sent_at)) FROM purchase_orders o JOIN po_lines p ON p.po_id=o.id
                JOIN movements m ON m.product_id=p.product_id AND m.kind='po_receipt' AND m.reference LIKE o.number||' / %'
                WHERE o.supplier_id=s.id) average_receipt_days FROM suppliers s''',(date.today().isoformat(),))]
            return {'stock':stock,'dead_stock':[r for r in stock if r['qty'] and not r['used_30_days']],
                    'margins':[dict(r,margin=r['subtotal']-r['cost']) for r in margins],'suppliers':suppliers}

    def accounting_export(self):
        """Signed document rows for generic accounting import, not a vendor-specific connector."""
        with self.connect() as db:
            rows=[]
            for i in db.execute('SELECT * FROM invoices ORDER BY id'):
                sign=-1 if i['kind']=='credit' else 1
                rows.append({'date':i['invoice_date'],'document':i['number'],'type':i['kind'],
                    'taxable_inr':amount(sign*i['subtotal']),'cgst_inr':amount(sign*i['cgst']),
                    'sgst_utgst_inr':amount(sign*i['sgst']),'igst_inr':amount(sign*i['igst']),'total_inr':amount(sign*i['total'])})
            for b in db.execute("SELECT * FROM bills WHERE state='accepted' ORDER BY id"):
                bill=self._bill_match(db,b['id'])
                rows.append({'date':b['bill_date'],'document':b['number'],'type':'supplier_bill','taxable_inr':amount(bill['subtotal']),
                    'freight_inr':amount(b['freight']),'purchase_tax_inr':amount(b['tax']),'total_inr':amount(bill['total'])})
            return csv_bytes(rows,['date','document','type','taxable_inr','cgst_inr','sgst_utgst_inr','igst_inr','freight_inr','purchase_tax_inr','total_inr'])

    def repairs(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT r.*,b.code,b.warranty_until,p.item_code FROM repairs r JOIN batches b ON b.id=r.batch_id JOIN products p ON p.id=b.product_id ORDER BY r.id DESC')]

    def save_repair(self,batch_id,customer,problem,*,actor,token):
        customer=text(customer,'Customer',required=True,limit=200); problem=text(problem,'Problem',required=True,limit=1000)
        payload=['repair',batch_id,customer,problem]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            b=db.execute('SELECT b.*,p.tracking FROM batches b JOIN products p ON p.id=b.product_id WHERE b.id=?',(batch_id,)).fetchone()
            if not b or b['tracking']!='serial':raise ValidationError('Choose a serial-tracked item.')
            rid=db.execute("INSERT INTO repairs(batch_id,customer,problem,created_at) VALUES(?,?,?,datetime('now'))",(batch_id,customer,problem)).lastrowid
            self._audit(db,actor,'repair_opened',rid,{'serial':b['code']})
            return self._done(db,token,payload,rid)

    def close_repair(self,repair_id,resolution,*,actor):
        resolution=text(resolution,'Resolution',required=True,limit=1000)
        with self.connect(True) as db:
            changed=db.execute("UPDATE repairs SET state='closed',resolution=? WHERE id=? AND state='open'",(resolution,repair_id)).rowcount
            if not changed:raise ValidationError('Repair is already closed or missing.')
            self._audit(db,actor,'repair_closed',repair_id,{'resolution':resolution})

    def refresh_alerts(self):
        current={}; today=date.today().isoformat(); soon=(date.today()+timedelta(days=30)).isoformat()
        with self.connect(True) as db:
            for o in db.execute("SELECT id,number,state FROM purchase_orders WHERE state IN ('draft','approved')"):
                current[f'approval:{o["id"]}']=('Purchase decision',f'{o["number"]}: '+('review and approve draft.' if o['state']=='draft' else 'approved and awaiting placement.'))
            for o in db.execute("SELECT * FROM purchase_orders WHERE state IN ('sent','partial','sending','delivery_unknown')"):
                if o['state'] in ('sending','delivery_unknown'):current[f'email:{o["id"]}']=('Delivery uncertainty',f'{o["number"]}: verify email delivery.')
                elif o['due_date'] and o['due_date']<today:current[f'po:{o["id"]}']=('Late delivery',f'{o["number"]} was due {o["due_date"]}.')
            for b in db.execute("SELECT id,number FROM bills WHERE state='review'"):
                matched=self._bill_match(db,b['id'])
                message=' '.join(matched['issues']) or 'Ready for bill review.'
                current[f'bill:{b["id"]}']=('Supplier bill',f'{b["number"]}: {message}')
            for b in db.execute('SELECT b.*,p.item_code FROM batches b JOIN products p ON p.id=b.product_id WHERE expiry<=?',(soon,)):
                stock=db.execute('SELECT COALESCE(SUM(delta),0) FROM movements WHERE batch_id=?',(b['id'],)).fetchone()[0]
                if stock>0:current[f'expiry:{b["id"]}']=('Batch expiry',f'{b["item_code"]} / {b["code"]}: {quantity(stock)} expires {b["expiry"]}.')
            for n in db.execute('SELECT * FROM loans WHERE returned<qty AND due_date<?',(today,)):
                current[f'loan:{n["id"]}']=('Returnable overdue',f'{n["holder"]}: {quantity(n["qty"]-n["returned"])} outstanding since {n["due_date"]}.')
            for j in db.execute('SELECT j.*,COALESCE(SUM(u.cost),0) cost FROM jobs j LEFT JOIN job_usage u ON u.job_id=j.id GROUP BY j.id'):
                if j['budget'] and j['cost']>j['budget']:current[f'job:{j["id"]}']=('Job budget',f'{j["name"]}: materials exceed budget by ₹{amount(j["cost"]-j["budget"])}.')
            for i in db.execute("SELECT i.*,COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id=i.id),0) paid,COALESCE((SELECT SUM(total) FROM invoices WHERE original_id=i.id),0) credited FROM invoices i WHERE kind='invoice' AND due_date<?",(today,)):
                if i['total']>i['paid']+i['credited']:current[f'invoice:{i["id"]}']=('Payment overdue',f'{i["number"]}: ₹{amount(i["total"]-i["paid"]-i["credited"])} overdue.')
            for p in db.execute('SELECT * FROM products'):
                available=self._available_internal(db,p['id'])
                if available<p['reorder_level']:current[f'stock:{p["id"]}']=('Low stock',f'{p["item_code"]}: {quantity(available)} available; reorder level {quantity(p["reorder_level"])}.')
                quotes=db.execute('SELECT price FROM quotes WHERE product_id=? ORDER BY id DESC LIMIT 2',(p['id'],)).fetchall()
                if len(quotes)==2 and quotes[0]['price']>quotes[1]['price']:
                    current[f'price:{p["id"]}']=('Price change',f'{p["item_code"]}: latest quote ₹{amount(quotes[0]["price"])}; previous quote ₹{amount(quotes[1]["price"])}. Compare supplier and terms.')
            for o in db.execute("SELECT * FROM sales_orders WHERE state IN ('confirmed','partial') AND delivery_date<?",(today,)):
                current[f'sales_due:{o["id"]}']=('Customer delivery',f'{o["number"]}: undelivered commitment due {o["delivery_date"]}.')
            for w in db.execute("SELECT * FROM work_orders WHERE state NOT IN ('completed','cancelled') AND due_date<?",(today,)):
                current[f'work_due:{w["id"]}']=('Production delay',f'{w["number"]}: {w["operator"]}, due {w["due_date"]}.')
            for q in db.execute('SELECT q.*,p.item_code,p.unit FROM quality_inspections q JOIN products p ON p.id=q.product_id WHERE held>0'):
                current[f'quality:{q["id"]}']=('Quality hold',f'QC-{q["id"]}: {q["item_code"]}, {quantity(q["held"])} {q["unit"]} held ({q["state"]}).')
            for j in db.execute("SELECT * FROM jobwork_orders WHERE state='open' AND due_date<?",(today,)):
                if db.execute('SELECT 1 FROM jobwork_materials WHERE job_id=? AND qty>returned+consumed+scrap',(j['id'],)).fetchone():
                    current[f'jobwork_due:{j["id"]}']=('Job-work return',f'{j["number"]}: material reconciliation overdue with {j["subcontractor"]}.')
            existing={r['key']:r for r in db.execute('SELECT * FROM alerts')}
            for key,(category,message) in current.items():
                prior=existing.get(key)
                if not prior:
                    db.execute("INSERT INTO alerts(key,category,message,created_at) VALUES(?,?,?,datetime('now'))",(key,category,message))
                elif prior['message']!=message or prior['resolved_at']:
                    db.execute("UPDATE alerts SET category=?,message=?,resolved_at=NULL,acknowledged=0,created_at=datetime('now') WHERE key=?",(category,message,key))
            for key in existing.keys()-current.keys():
                if not key.startswith('import:'):
                    db.execute("UPDATE alerts SET resolved_at=COALESCE(resolved_at,datetime('now')) WHERE key=?",(key,))
        return len(current)

    def record_import_issue(self, fingerprint, message, *, actor):
        fingerprint=text(fingerprint,'Import fingerprint',required=True,limit=100)
        message=text(message,'Import errors',required=True,limit=4000)
        with self.connect(True) as db:
            key='import:'+fingerprint
            db.execute("INSERT OR IGNORE INTO alerts(key,category,message,created_at) VALUES(?,'Rejected import',?,datetime('now'))",(key,message))

    def alerts(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM alerts WHERE resolved_at IS NULL ORDER BY acknowledged,category,created_at')]

    def acknowledge_alert(self,key,*,actor):
        with self.connect(True) as db:
            db.execute('UPDATE alerts SET acknowledged=1 WHERE key=?',(key,))
            if key.startswith('import:'):
                db.execute("UPDATE alerts SET resolved_at=datetime('now') WHERE key=?",(key,))
            self._audit(db,actor,'alert_acknowledged',key,{})

    def run_maintenance(self,*,actor):
        self.refresh_alerts()
        settings=self.settings()
        if settings.get('backup_enabled')!='true':return 'Alerts refreshed. Automatic backup is disabled.'
        interval=int(settings.get('backup_days','1'))
        last=settings.get('last_backup','')
        if last and (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()<interval*86400:
            return 'Alerts refreshed; backup is not yet due.'
        folder=self.path.parent/'backups'; folder.mkdir(exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        target=folder/f'stocklist-{stamp}.sqlite3'
        content=self.backup()
        with target.open('xb') as f:f.write(content)
        with self.connect(True) as db:
            db.execute("INSERT INTO settings VALUES('last_backup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(datetime.now(timezone.utc).isoformat(),))
            self._audit(db,actor,'automatic_backup_saved',target.name,{'bytes':len(content)})
        return f'Backup saved: {target.name}. Alerts refreshed.'

    def sync_movements(self,rows,*,actor):
        """Offline queue replay: each row has a permanent client id; failed rows remain retryable."""
        if not isinstance(rows,list) or len(rows)>1000 or any(not isinstance(r,dict) for r in rows):raise ValidationError('Upload at most 1,000 queued stock movements.')
        results=[]
        with self.connect() as db:
            products={r['item_code'].casefold():dict(r) for r in db.execute('SELECT * FROM products')}
            locations={r['name'].casefold():r['id'] for r in db.execute('SELECT * FROM locations')}
            workspace_id=db.execute("SELECT value FROM settings WHERE key='workspace_id'").fetchone()[0]
        for row in rows:
            try:
                client_id=text(row.get('id'),'Offline transaction ID',required=True,limit=100)
                if row.get('workspace_id')!=workspace_id:raise ValidationError('This queue belongs to another business database. Use a sheet downloaded from this workspace.')
                product=products.get(str(row.get('sku','')).casefold()); lid=locations.get(str(row.get('location','')).casefold())
                if not product or lid is None:raise ValidationError('Unknown SKU or location.')
                if row.get('kind') not in ('receipt','sale','issue','customer_return','supplier_return','damage'):
                    raise ValidationError('Offline queue supports receipts, sales, issues, returns and damage.')
                result=self.move_stock(product['id'],row['kind'],row.get('quantity',''),row.get('reason',''),actor=actor,
                    token='offline:'+client_id,reference=row.get('reference',''),location_id=lid,batch_id=row.get('batch_id'))
                results.append({'id':client_id,'status':'applied','record':str(result)})
            except (ValidationError,KeyError) as exc:
                results.append({'id':row.get('id',''),'status':'needs review','message':str(exc)})
        return results
