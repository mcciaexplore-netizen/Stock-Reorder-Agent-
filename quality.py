"""Quantity-based quarantine, inspection and rework, enforced by the stock ledger."""
from datetime import date
from inventory import ValidationError, scaled, text


class Quality:
    @staticmethod
    def _held(db, product_id, location_id=None, batch_id=None, usable_only=False):
        sql='''SELECT COALESCE(SUM(q.held),0) FROM quality_inspections q JOIN locations l ON l.id=q.location_id
            LEFT JOIN batches b ON b.id=q.batch_id WHERE q.product_id=?'''
        args=[product_id]
        if location_id is not None:sql+=' AND q.location_id=?'; args.append(location_id)
        elif usable_only:sql+=" AND l.kind IN ('warehouse','shop')"
        if batch_id is not None:sql+=' AND q.batch_id=?'; args.append(batch_id)
        if usable_only:sql+=' AND (b.expiry IS NULL OR b.expiry>=?)'; args.append(date.today().isoformat())
        return db.execute(sql,args).fetchone()[0]

    def _open_inspection(self, db, product_id, location_id, batch_id, qty, stage, reference, actor, work_id=None):
        p=self._product(db,product_id); self._location(db,location_id)
        if stage not in ('incoming','production','final'):raise ValidationError('Choose incoming, production or final inspection.')
        if p['tracking']!='none':
            b=db.execute('SELECT * FROM batches WHERE id=? AND product_id=?',(batch_id,product_id)).fetchone()
            if not b:raise ValidationError('Select the batch or serial being inspected.')
        elif batch_id is not None:raise ValidationError('This product does not use batch tracking.')
        if qty<=0 or (p['tracking']=='serial' and qty!=1000):raise ValidationError('Enter a positive quantity, or exactly one for a serial number.')
        free=self._local_balance(db,product_id,location_id)-self._reserved(db,product_id,location_id)-self._held(db,product_id,location_id)
        batch_free=self._local_balance(db,product_id,location_id,batch_id)-self._held(db,product_id,location_id,batch_id)
        if qty>min(free,batch_free):raise ValidationError('Inspection quantity exceeds unreserved stock not already in quarantine.')
        if work_id is not None:
            w=self._work(db,work_id)
            if w['product_id']!=product_id or w['location_id']!=location_id:raise ValidationError('The work order output and location must match the inspection.')
        qid=db.execute("""INSERT INTO quality_inspections(product_id,location_id,batch_id,work_id,stage,reference,qty,held,created_at)
            VALUES(?,?,?,?,?,?,?,?,datetime('now'))""",(product_id,location_id,batch_id,work_id,stage,reference,qty,qty)).lastrowid
        self._audit(db,actor,'quality_hold_created',qid,{'qty':qty,'stage':stage,'reference':reference})
        return qid

    def open_quality_inspection(self, product_id, location_id, qty, stage, reference, batch_id=None, work_id=None, *, actor, token):
        qty=scaled(qty); reference=text(reference,'Receipt / production / dispatch reference',required=True,limit=200)
        payload=['quality_hold',product_id,location_id,qty,stage,reference,batch_id,work_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            qid=self._open_inspection(db,product_id,location_id,batch_id,qty,stage,reference,actor,work_id)
            return self._done(db,token,payload,qid)

    def quality_inspections(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT q.*,p.item_name,p.item_code,p.unit,l.name location,b.code batch
                FROM quality_inspections q JOIN products p ON p.id=q.product_id JOIN locations l ON l.id=q.location_id
                LEFT JOIN batches b ON b.id=q.batch_id ORDER BY q.id DESC''')]

    def quality_history(self, inspection_id):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM quality_events WHERE inspection_id=? ORDER BY id',(inspection_id,))]

    def record_quality_result(self, inspection_id, accepted, rejected, notes, *, actor, token):
        accepted=scaled(accepted,'Accepted quantity'); rejected=scaled(rejected,'Rejected quantity')
        notes=text(notes,'Inspection observations / measurements',required=True,limit=2000)
        payload=['quality_result',inspection_id,accepted,rejected,notes]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            q=db.execute('SELECT * FROM quality_inspections WHERE id=?',(inspection_id,)).fetchone()
            if not q or q['state'] not in ('awaiting','rework') or accepted+rejected!=q['held']:
                raise ValidationError('Accepted plus rejected must equal the quantity awaiting inspection or reinspection.')
            db.execute('UPDATE quality_inspections SET accepted=accepted+?,held=?,state=? WHERE id=?',
                (accepted,rejected,'rejected' if rejected else 'closed',inspection_id))
            db.execute("INSERT INTO quality_events(inspection_id,action,accepted,rejected,notes,actor,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                (inspection_id,'reinspection' if q['state']=='rework' else 'inspection',accepted,rejected,notes,actor))
            self._audit(db,actor,'quality_result',inspection_id,{'accepted':accepted,'rejected':rejected,'notes':notes})
            return self._done(db,token,payload,inspection_id)

    def route_quality_rework(self, inspection_id, notes, *, actor):
        notes=text(notes,'Rework instructions',required=True,limit=1000)
        with self.connect(True) as db:
            if not db.execute("UPDATE quality_inspections SET state='rework' WHERE id=? AND state='rejected' AND held>0",(inspection_id,)).rowcount:
                raise ValidationError('Only rejected stock can enter rework.')
            db.execute("INSERT INTO quality_events(inspection_id,action,notes,actor,created_at) VALUES(?,'rework',?,?,datetime('now'))",(inspection_id,notes,actor))
            self._audit(db,actor,'quality_rework',inspection_id,{'notes':notes})

    def dispose_quality_stock(self, inspection_id, qty, reason, *, actor, token):
        qty=scaled(qty); reason=text(reason,'Disposal reason',required=True,limit=500)
        payload=['quality_dispose',inspection_id,qty,reason]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            q=db.execute("SELECT * FROM quality_inspections WHERE id=? AND state IN ('rejected','rework')",(inspection_id,)).fetchone()
            if not q or qty<=0 or qty>q['held']:raise ValidationError('Disposal exceeds rejected stock or is zero.')
            db.execute('UPDATE quality_inspections SET held=held-?,disposed=disposed+?,state=? WHERE id=?',
                (qty,qty,'closed' if qty==q['held'] else q['state'],inspection_id))
            mid=self._movement(db,q['product_id'],-qty,'damage',reason,f'QC-{inspection_id}',actor,location_id=q['location_id'],batch_id=q['batch_id'])
            db.execute("INSERT INTO quality_events(inspection_id,action,rejected,notes,actor,created_at) VALUES(?,'disposed',?,?,?,datetime('now'))",(inspection_id,qty,reason,actor))
            self._audit(db,actor,'quality_disposed',inspection_id,{'qty':qty,'movement':mid})
            return self._done(db,token,payload,mid)
