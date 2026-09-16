"""Challans and ownership-aware material custody with subcontractor reconciliation."""
import html
from inventory import ValidationError, quantity, scaled, text
from inventory_ops import day


class Jobwork:
    def create_jobwork(self, owner, customer_id, subcontractor, location_id, due_date, reference, *, actor, token):
        if owner not in ('company','customer'):raise ValidationError('Choose company or customer ownership.')
        subcontractor=text(subcontractor,'Subcontractor / processing site',required=True,limit=100)
        reference=text(reference,'Job reference',required=True,limit=200); due_date=day(due_date)
        payload=['jobwork',owner,customer_id,subcontractor,location_id,due_date,reference]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            self._location(db,location_id)
            if customer_id is not None and not db.execute('SELECT 1 FROM customers WHERE id=?',(customer_id,)).fetchone():raise ValidationError('Choose an existing customer.')
            if owner=='customer' and customer_id is None:raise ValidationError('Identify the customer who owns these materials.')
            jid=db.execute("""INSERT INTO jobwork_orders(owner,customer_id,subcontractor,location_id,holder_location,due_date,reference,created_at)
                VALUES(?,?,?,?,?,?,?,datetime('now'))""",(owner,customer_id,subcontractor,location_id,location_id,due_date,reference)).lastrowid
            # A dedicated location isolates company stock for this contract from unrelated transfers.
            holder=db.execute("INSERT INTO locations(name,kind,contact) VALUES(?,'jobwork',?)",(f'Job work {jid} · {subcontractor}',subcontractor)).lastrowid
            db.execute('UPDATE jobwork_orders SET number=?,holder_location=? WHERE id=?',(f'JW-{jid:06d}',holder,jid))
            self._audit(db,actor,'jobwork_created',jid,{'owner':owner,'customer':customer_id})
            return self._done(db,token,payload,jid)

    @staticmethod
    def _jobwork(db, job_id):
        j=db.execute("SELECT * FROM jobwork_orders WHERE id=? AND state='open'",(job_id,)).fetchone()
        if not j:raise ValidationError('Choose an open job-work order.')
        return dict(j)

    @staticmethod
    def _jobwork_event(db, material_id, action, qty, reference, actor):
        eid=db.execute("INSERT INTO jobwork_events(material_id,action,qty,reference,actor,created_at) VALUES(?,?,?,?,?,datetime('now'))",
            (material_id,action,qty,reference,actor)).lastrowid
        db.execute('UPDATE jobwork_events SET number=? WHERE id=?',(f'JC-{eid:06d}',eid))
        return eid

    def receive_jobwork_material(self, job_id, product_id, qty, reference, batch_id=None, *, actor, token):
        qty=scaled(qty); reference=text(reference,'Challan reference',required=True,limit=200)
        payload=['jobwork_material',job_id,product_id,qty,reference,batch_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            j=self._jobwork(db,job_id); p=self._product(db,product_id)
            if qty<=0:raise ValidationError('Enter a positive material quantity.')
            if p['tracking']!='none':
                if not db.execute('SELECT 1 FROM batches WHERE id=? AND product_id=?',(batch_id,product_id)).fetchone():raise ValidationError('Choose the material batch or serial.')
                if p['tracking']=='serial' and qty!=1000:raise ValidationError('A serial number represents exactly one item.')
            elif batch_id is not None:raise ValidationError('This product does not use batches.')
            if j['owner']=='company':
                ids=self._take(db,product_id,qty,j['location_id'],'jobwork_out','Company material sent for processing',j['number'],actor,batch_id)
                for mid in ids:
                    m=db.execute('SELECT * FROM movements WHERE id=?',(mid,)).fetchone()
                    self._movement(db,product_id,-m['delta'],'jobwork_in','Company stock with subcontractor',j['number'],actor,
                        location_id=j['holder_location'],batch_id=m['batch_id'],total_cost=-m['value_delta'],custody=True)
            elif p['tracking']=='serial' and db.execute('''SELECT 1 FROM jobwork_materials m JOIN jobwork_orders o ON o.id=m.job_id
                WHERE o.owner='customer' AND o.customer_id=? AND m.batch_id=? AND m.qty>m.returned+m.consumed+m.scrap''',(j['customer_id'],batch_id)).fetchone():
                raise ValidationError('This customer serial is already held in custody.')
            mid=db.execute('INSERT INTO jobwork_materials(job_id,product_id,batch_id,qty,outside) VALUES(?,?,?,?,?)',
                (job_id,product_id,batch_id,qty,qty if j['owner']=='company' else 0)).lastrowid
            eid=self._jobwork_event(db,mid,'company_outward' if j['owner']=='company' else 'customer_inward',qty,reference,actor)
            self._audit(db,actor,'jobwork_material_recorded',mid,{'qty':qty,'owner':j['owner'],'challan':eid})
            return self._done(db,token,payload,mid)

    def reconcile_jobwork(self, material_id, action, qty, reference, *, actor, token):
        if action not in ('send','return','customer_return','consume','scrap'):raise ValidationError('Choose a supported job-work movement.')
        qty=scaled(qty); reference=text(reference,'Challan / reconciliation reference',required=True,limit=200)
        payload=['jobwork_reconcile',material_id,action,qty,reference]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            m=db.execute('SELECT * FROM jobwork_materials WHERE id=?',(material_id,)).fetchone()
            if not m:raise ValidationError('Choose a job-work material line.')
            j=self._jobwork(db,m['job_id'])
            onsite=m['qty']-m['outside']-m['returned']-m['consumed']-m['scrap']
            limit=onsite if action in ('send','customer_return') else m['outside']
            if qty<=0 or qty>limit:raise ValidationError('Quantity exceeds the material held at the source site.')
            if action in ('send','customer_return') and j['owner']!='customer':
                raise ValidationError('Use a new outward challan for company materials.')
            if j['owner']=='company':
                mid=self._movement(db,m['product_id'],-qty,'jobwork_return' if action=='return' else 'jobwork_'+action,
                    'Job-work reconciliation',j['number'],actor,location_id=j['holder_location'],batch_id=m['batch_id'],custody=True)
                cost=-db.execute('SELECT value_delta FROM movements WHERE id=?',(mid,)).fetchone()[0]
                if action=='return':self._movement(db,m['product_id'],qty,'jobwork_return','Material returned from subcontractor',j['number'],actor,
                    location_id=j['location_id'],batch_id=m['batch_id'],total_cost=cost)
            if action=='send':db.execute('UPDATE jobwork_materials SET outside=outside+? WHERE id=?',(qty,material_id))
            elif action=='return':
                db.execute('UPDATE jobwork_materials SET outside=outside-?,returned=returned+? WHERE id=?',(qty,qty if j['owner']=='company' else 0,material_id))
            elif action=='customer_return':db.execute('UPDATE jobwork_materials SET returned=returned+? WHERE id=?',(qty,material_id))
            else:
                column='consumed' if action=='consume' else 'scrap'
                db.execute(f'UPDATE jobwork_materials SET outside=outside-?,{column}={column}+? WHERE id=?',(qty,qty,material_id))
            eid=self._jobwork_event(db,material_id,action,qty,reference,actor)
            self._audit(db,actor,'jobwork_reconciled',material_id,{'action':action,'qty':qty,'challan':eid})
            return self._done(db,token,payload,eid)

    def jobwork_orders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT j.*,c.name customer FROM jobwork_orders j LEFT JOIN customers c ON c.id=j.customer_id ORDER BY j.id DESC')]

    def jobwork_materials(self, job_id):
        with self.connect() as db:
            return [dict(r,onsite=r['qty']-r['outside']-r['returned']-r['consumed']-r['scrap']) for r in db.execute('''SELECT m.*,p.item_name,p.item_code,p.unit,b.code batch
                FROM jobwork_materials m JOIN products p ON p.id=m.product_id LEFT JOIN batches b ON b.id=m.batch_id WHERE m.job_id=?''',(job_id,))]

    def jobwork_challans(self, job_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT e.*,p.item_name,p.unit FROM jobwork_events e JOIN jobwork_materials m ON m.id=e.material_id
                JOIN products p ON p.id=m.product_id WHERE m.job_id=? ORDER BY e.id DESC''',(job_id,))]

    def close_jobwork(self, job_id, *, actor):
        with self.connect(True) as db:
            self._jobwork(db,job_id)
            if db.execute('SELECT 1 FROM jobwork_materials WHERE job_id=? AND qty>returned+consumed+scrap',(job_id,)).fetchone():
                raise ValidationError('Reconcile all material as returned, consumed or scrapped before closing.')
            db.execute("UPDATE jobwork_orders SET state='closed' WHERE id=?",(job_id,))
            self._audit(db,actor,'jobwork_closed',job_id,{})

    def jobwork_document(self, event_id):
        with self.connect() as db:
            r=db.execute('''SELECT e.*,j.number job_number,j.owner,j.reference job_reference,j.subcontractor,c.name customer,
                p.item_name,p.item_code,p.unit,b.code batch FROM jobwork_events e JOIN jobwork_materials m ON m.id=e.material_id
                JOIN jobwork_orders j ON j.id=m.job_id JOIN products p ON p.id=m.product_id LEFT JOIN batches b ON b.id=m.batch_id
                LEFT JOIN customers c ON c.id=j.customer_id WHERE e.id=?''',(event_id,)).fetchone()
            if not r:raise ValidationError('Choose a challan.')
            esc=lambda v:html.escape(str(v or ''))
            return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{esc(r['number'])}</title>
                <style>body{{font:16px system-ui;margin:40px;color:#203b50}}dt{{font-weight:bold}}dd{{margin-bottom:16px}}</style>
                <h1>Job-work material record · {esc(r['number'])}</h1><p>{esc(r['created_at'])}</p>
                <dl><dt>Job / reference</dt><dd>{esc(r['job_number'])} / {esc(r['job_reference'])}</dd>
                <dt>Material owner</dt><dd>{esc(r['customer'] if r['owner']=='customer' else 'Company')}</dd>
                <dt>Subcontractor / processing site</dt><dd>{esc(r['subcontractor'])}</dd>
                <dt>Movement</dt><dd>{esc(r['action'].replace('_',' '))}</dd><dt>Material</dt><dd>{esc(r['item_name'])} · {esc(r['item_code'])} · {esc(r['batch'])}</dd>
                <dt>Quantity</dt><dd>{quantity(r['qty'])} {esc(r['unit'])}</dd><dt>Challan reference</dt><dd>{esc(r['reference'])}</dd></dl>
                <p>Issued by: {esc(r['actor'])}</p><p>Received by: ____________________</p><p>Operational material record; not a tax invoice or government filing.</p></html>'''.encode('utf-8')
