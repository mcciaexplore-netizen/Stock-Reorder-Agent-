"""Locations, traceability, reservations and manufacturing transactions."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json

from inventory import ValidationError, amount, quantity, scaled, text


def day(value, label='Date', optional=False):
    value = text(value, label, required=not optional, limit=10)
    if not value and optional:
        return ''
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValidationError(f'{label} must use YYYY-MM-DD.') from None


def rounded(numerator, denominator):
    return int((Decimal(numerator)/denominator).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class InventoryOps:
    @staticmethod
    def _location(db, location_id):
        row = db.execute('SELECT * FROM locations WHERE id=?',(location_id,)).fetchone()
        if not row:
            raise ValidationError('Choose an existing stock location.')
        return dict(row)

    @staticmethod
    def _local_balance(db, product_id, location_id, batch_id=None):
        sql = 'SELECT COALESCE(SUM(delta),0) FROM movements WHERE product_id=? AND location_id=?'
        args = [product_id,location_id]
        if batch_id is not None:
            sql += ' AND batch_id=?'
            args.append(batch_id)
        return db.execute(sql,args).fetchone()[0]

    @staticmethod
    def _reserved(db, product_id, location_id=None):
        sql = "SELECT COALESCE(SUM(qty),0) FROM reservations WHERE state='open' AND product_id=?"
        args = [product_id]
        if location_id is not None:
            sql += ' AND location_id=?'
            args.append(location_id)
        return db.execute(sql,args).fetchone()[0]

    def _usable_balance(self, db, product_id, location_id=None):
        sql='''SELECT COALESCE(SUM(m.delta),0) FROM movements m JOIN locations l ON l.id=m.location_id
            LEFT JOIN batches b ON b.id=m.batch_id WHERE m.product_id=? AND (b.expiry IS NULL OR b.expiry>=?)'''
        args=[product_id,date.today().isoformat()]
        if location_id is None:
            sql+=" AND l.kind IN ('warehouse','shop')"
        else:
            sql+=' AND m.location_id=?'; args.append(location_id)
        return db.execute(sql,args).fetchone()[0]-self._held(db,product_id,location_id,usable_only=True)

    def _available_internal(self,db,product_id):
        reserved=db.execute("SELECT COALESCE(SUM(r.qty),0) FROM reservations r JOIN locations l ON l.id=r.location_id WHERE r.product_id=? AND r.state='open' AND l.kind IN ('warehouse','shop')",(product_id,)).fetchone()[0]
        return self._usable_balance(db,product_id)-reserved

    def locations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM locations ORDER BY id')]

    def save_location(self, name, kind='warehouse', contact='', *, actor):
        if kind not in ('warehouse','shop','subcontractor','consignment','returnable'):
            raise ValidationError('Choose a supported location type.')
        with self.connect(True) as db:
            lid = db.execute('INSERT INTO locations(name,kind,contact) VALUES(?,?,?)',
                (text(name,'Location name',required=True,limit=100),kind,text(contact,'Contact',limit=200))).lastrowid
            self._audit(db,actor,'location_created',lid,{'kind':kind})
            return lid

    def location_stock(self, location_id=None):
        with self.connect() as db:
            rows = db.execute('''SELECT v.*,p.item_code,p.item_name,p.unit,l.name location,l.kind,
                COALESCE((SELECT SUM(r.qty) FROM reservations r WHERE r.product_id=v.product_id
                AND r.location_id=v.location_id AND r.state='open'),0) reserved
                FROM valuations v JOIN products p ON p.id=v.product_id JOIN locations l ON l.id=v.location_id
                ''' + ('WHERE v.location_id=? ' if location_id is not None else '') + 'ORDER BY l.name,p.item_name',
                (location_id,) if location_id is not None else ()).fetchall()
            return [dict(r,held=self._held(db,r['product_id'],r['location_id']),
                available=r['qty']-r['reserved']-self._held(db,r['product_id'],r['location_id'])) for r in rows]

    def save_product_options(self, product_id, tracking, attributes, hsn, tax_rate, min_order='0', pack_size='0.001', safety_stock='0', *, actor):
        if tracking not in ('none','batch','serial'):
            raise ValidationError('Choose no tracking, batch or serial tracking.')
        if not isinstance(attributes,dict) or len(attributes)>30:
            raise ValidationError('Custom fields must be an object with at most 30 fields.')
        attrs = {text(k,'Field name',required=True,limit=80):text(v,'Field value',limit=500) for k,v in attributes.items()}
        tax = scaled(tax_rate,'Tax rate',100)
        minimum, pack, safety = scaled(min_order),scaled(pack_size),scaled(safety_stock)
        if tax>10000 or pack<=0:
            raise ValidationError('Tax must be 0–100%; pack size must be positive.')
        with self.connect(True) as db:
            old = self._product(db,product_id)
            if old['tracking']!=tracking:
                if self._balance(db,product_id) or db.execute('SELECT 1 FROM batches WHERE product_id=?',(product_id,)).fetchone():
                    raise ValidationError('Choose tracking before receiving stock or creating batches. Existing tracked history cannot be reclassified.')
            db.execute('UPDATE products SET tracking=?,attributes=?,hsn=?,tax_rate=?,min_order=?,pack_size=?,safety_stock=?,version=version+1 WHERE id=?',
                (tracking,json.dumps(attrs,ensure_ascii=False),text(hsn,'HSN',limit=12),tax,minimum,pack,safety,product_id))
            self._audit(db,actor,'product_options_saved',product_id,{'tracking':tracking,'attributes':attrs})

    def save_conversion(self, product_id, unit, factor, *, actor):
        factor = scaled(factor,'Base units per alternate unit')
        if factor<=0:
            raise ValidationError('Conversion factor must be positive.')
        with self.connect(True) as db:
            product = self._product(db,product_id)
            unit = text(unit,'Alternate unit',required=True,limit=40)
            if unit.casefold()==product['unit'].casefold():
                raise ValidationError('The base stock unit already has a fixed conversion of one.')
            db.execute('INSERT INTO conversions VALUES(?,?,?) ON CONFLICT(product_id,unit) DO UPDATE SET factor=excluded.factor',(product_id,unit,factor))
            self._audit(db,actor,'unit_conversion_saved',product_id,{'unit':unit,'factor':factor})

    def conversions(self, product_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM conversions WHERE product_id=?',(product_id,))]

    def _converted(self, db, product_id, qty, unit):
        if not unit or unit.casefold()==self._product(db,product_id)['unit'].casefold():
            return qty
        row = db.execute('SELECT factor FROM conversions WHERE product_id=? AND unit=?',(product_id,unit)).fetchone()
        if not row:
            raise ValidationError('Set up this unit conversion first.')
        result, remainder = divmod(qty*row[0],1000)
        if remainder:
            raise ValidationError('Converted quantity needs more than three decimal places.')
        return result

    def save_batch(self, product_id, code, expiry='', warranty_until='', *, actor):
        with self.connect(True) as db:
            product = self._product(db,product_id)
            if product['tracking']=='none':
                raise ValidationError('Enable batch or serial tracking for this product first.')
            bid = db.execute('INSERT INTO batches(product_id,code,expiry,warranty_until) VALUES(?,?,?,?)',
                (product_id,text(code,'Batch / serial number',required=True,limit=100),day(expiry,optional=True) or None,day(warranty_until,optional=True) or None)).lastrowid
            self._audit(db,actor,'batch_created',bid,{'product':product_id})
            return bid

    def batches(self, product_id=None, location_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT b.*,p.item_code,p.item_name,p.tracking FROM batches b JOIN products p ON p.id=b.product_id '+
                ('WHERE b.product_id=? ' if product_id else '')+'ORDER BY b.expiry IS NULL,b.expiry,b.id',(product_id,) if product_id else ()).fetchall()
            return [dict(r,stock=(self._local_balance(db,r['product_id'],location_id,r['id']) if location_id else
                    db.execute('SELECT COALESCE(SUM(delta),0) FROM movements WHERE batch_id=?',(r['id'],)).fetchone()[0])) for r in rows]

    def _take(self, db, product_id, qty, location_id, kind, reason, reference, actor, batch_id=None):
        """Issue using earliest expiry first; expired goods are excluded from normal dispatch."""
        product = self._product(db,product_id)
        if product['tracking']=='none' or batch_id is not None:
            return [self._movement(db,product_id,-qty,kind,reason,reference,actor,location_id=location_id,batch_id=batch_id)]
        allocations=[]
        for batch in db.execute('SELECT * FROM batches WHERE product_id=? AND (expiry IS NULL OR expiry>=?) ORDER BY expiry IS NULL,expiry,id',(product_id,date.today().isoformat())).fetchall():
            available=self._local_balance(db,product_id,location_id,batch['id'])-self._held(db,product_id,location_id,batch['id'])
            take=min(qty,available)
            if take:
                allocations.append(self._movement(db,product_id,-take,kind,reason,reference,actor,location_id=location_id,batch_id=batch['id']))
                qty-=take
            if not qty:
                return allocations
        raise ValidationError('Insufficient unexpired batch / serial stock at this location.')

    def transfer(self, product_id, qty, source, destination, reference, *, actor, token, batch_id=None):
        qty=scaled(qty)
        if qty<=0 or source==destination:
            raise ValidationError('Use a positive quantity and two different locations.')
        reference=text(reference,'Transfer reference',required=True,limit=200)
        payload=['transfer',product_id,qty,source,destination,reference,batch_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:
                return prior
            self._location(db,destination)
            ids=self._take(db,product_id,qty,source,'transfer_out','Stock transfer',reference,actor,batch_id)
            for mid in ids:
                m=db.execute('SELECT * FROM movements WHERE id=?',(mid,)).fetchone()
                self._movement(db,product_id,-m['delta'],'transfer_in','Stock transfer',reference,actor,
                    location_id=destination,batch_id=m['batch_id'],total_cost=-m['value_delta'])
            self._audit(db,actor,'stock_transferred',product_id,{'from':source,'to':destination,'qty':qty})
            return self._done(db,token,payload,ids)

    def reserve(self, product_id, qty, location_id, reference, *, actor, token):
        qty=scaled(qty)
        reference=text(reference,'Reservation reference',required=True,limit=200)
        payload=['reserve',product_id,qty,location_id,reference]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            if qty<=0 or qty>self._usable_balance(db,product_id,location_id)-self._reserved(db,product_id,location_id):
                raise ValidationError('Reservation exceeds available stock or is zero.')
            rid=db.execute("INSERT INTO reservations(product_id,location_id,qty,reference,created_at) VALUES(?,?,?,?,datetime('now'))",(product_id,location_id,qty,reference)).lastrowid
            self._audit(db,actor,'stock_reserved',rid,{'qty':qty})
            return self._done(db,token,payload,rid)

    def reservations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT r.*,p.item_code,l.name location FROM reservations r JOIN products p ON p.id=r.product_id JOIN locations l ON l.id=r.location_id ORDER BY r.id DESC')]

    def release_reservation(self, reservation_id, *, actor, fulfill=False):
        with self.connect(True) as db:
            r=db.execute("SELECT * FROM reservations WHERE id=? AND state='open'",(reservation_id,)).fetchone()
            if not r:raise ValidationError('This reservation is already closed.')
            db.execute('UPDATE reservations SET state=? WHERE id=?',('fulfilled' if fulfill else 'released',reservation_id))
            if fulfill:self._take(db,r['product_id'],r['qty'],r['location_id'],'issue','Reserved stock dispatched',r['reference'],actor)
            self._audit(db,actor,'reservation_closed',reservation_id,{'fulfilled':fulfill})

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT j.*,COALESCE((SELECT SUM(cost) FROM job_usage u WHERE u.job_id=j.id),0) material_cost FROM jobs j ORDER BY j.id DESC')]

    def save_job(self, name, customer='', budget='0', *, actor):
        with self.connect(True) as db:
            jid=db.execute('INSERT INTO jobs(name,customer,budget) VALUES(?,?,?)',(text(name,'Job name',required=True,limit=200),text(customer,limit=200),scaled(budget,'Budget',100))).lastrowid
            self._audit(db,actor,'job_created',jid,{})
            return jid

    def consume_job(self, job_id, product_id, qty, location_id, *, actor, token):
        qty=scaled(qty)
        payload=['job_use',job_id,product_id,qty,location_id]
        with self.connect(True) as db:
            previous=self._once(db,token,payload)
            if previous is not None:return previous
            job=db.execute("SELECT * FROM jobs WHERE id=? AND state='open'",(job_id,)).fetchone()
            if not job or qty<=0:raise ValidationError('Choose an open job and a positive quantity.')
            ids=self._take(db,product_id,qty,location_id,'job_issue','Material consumed for job',job['name'],actor)
            cost=0
            for mid in ids:
                value=-db.execute('SELECT value_delta FROM movements WHERE id=?',(mid,)).fetchone()[0]
                db.execute('INSERT INTO job_usage(job_id,movement_id,cost) VALUES(?,?,?)',(job_id,mid,value))
                cost+=value
            self._audit(db,actor,'job_material_consumed',job_id,{'qty':qty,'cost':cost})
            return self._done(db,token,payload,cost)

    def recipes(self, product_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT r.*,p.item_code,p.item_name,p.unit FROM recipes r JOIN products p ON p.id=r.component_id WHERE r.product_id=?',(product_id,))]

    def save_recipe(self, product_id, components, *, actor):
        with self.connect(True) as db:
            self._product(db,product_id)
            if not components:raise ValidationError('Add at least one component.')
            db.execute('DELETE FROM recipes WHERE product_id=?',(product_id,))
            for c in components:
                qty=scaled(c['qty'],'Component quantity')
                if qty<=0:raise ValidationError('Component quantities must be positive.')
                db.execute('INSERT INTO recipes VALUES(?,?,?)',(product_id,c['product_id'],qty))
            cycle=db.execute('''WITH RECURSIVE parts(id) AS (SELECT component_id FROM recipes WHERE product_id=?
                UNION SELECT r.component_id FROM recipes r JOIN parts p ON r.product_id=p.id)
                SELECT 1 FROM parts WHERE id=?''',(product_id,product_id)).fetchone()
            if cycle:raise ValidationError('A bill of materials cannot contain a cycle.')
            self._audit(db,actor,'recipe_saved',product_id,components)

    def assemble(self, product_id, qty, location_id, reference, overhead='0', batch_id=None, *, actor, token):
        qty=scaled(qty); overhead=scaled(overhead,'Production overhead',100)
        reference=text(reference,'Production reference',required=True,limit=200)
        payload=['assemble',product_id,qty,location_id,reference,overhead,batch_id]
        with self.connect(True) as db:
            previous=self._once(db,token,payload)
            if previous is not None:return previous
            recipe=db.execute('SELECT * FROM recipes WHERE product_id=?',(product_id,)).fetchall()
            if not recipe or qty<=0:raise ValidationError('Save a bill of materials and enter positive output.')
            cost=overhead
            for c in recipe:
                needed,remainder=divmod(c['qty']*qty,1000)
                if remainder:raise ValidationError('Component quantity needs more than three decimal places.')
                ids=self._take(db,c['component_id'],needed,location_id,'production_issue','Production consumption',reference,actor)
                cost-=sum(db.execute('SELECT value_delta FROM movements WHERE id=?',(mid,)).fetchone()[0] for mid in ids)
            self._movement(db,product_id,qty,'production_receipt','Production output',reference,actor,location_id=location_id,batch_id=batch_id,total_cost=cost)
            self._audit(db,actor,'production_completed',product_id,{'qty':qty,'cost':cost,'reference':reference})
            return self._done(db,token,payload,cost)

    def loans(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT n.*,p.item_code,p.item_name FROM loans n JOIN products p ON p.id=n.product_id ORDER BY n.id DESC')]

    def lend(self, product_id, qty, location_id, holder, due_date, reference, *, actor, token, batch_id=None):
        qty=scaled(qty); holder=text(holder,'Holder',required=True,limit=100)
        due_date=day(due_date); reference=text(reference,'Reference',required=True,limit=200)
        payload=['lend',product_id,qty,location_id,holder,due_date,reference,batch_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            if qty<=0:raise ValidationError('Quantity must be positive.')
            product=self._product(db,product_id)
            if product['tracking']!='none' and batch_id is None:raise ValidationError('Choose the batch / serial being lent.')
            name='Returnables · '+holder
            db.execute("INSERT OR IGNORE INTO locations(name,kind,contact) VALUES(?,'returnable',?)",(name,holder))
            target=db.execute('SELECT id FROM locations WHERE name=?',(name,)).fetchone()[0]
            ids=self._take(db,product_id,qty,location_id,'loan_out','Returnable dispatched',reference,actor,batch_id)
            cost=-sum(db.execute('SELECT value_delta FROM movements WHERE id=?',(m,)).fetchone()[0] for m in ids)
            self._movement(db,product_id,qty,'loan_in','Held by customer',reference,actor,location_id=target,batch_id=batch_id,total_cost=cost)
            lid=db.execute('INSERT INTO loans(product_id,location_id,holder_location,qty,holder,due_date,reference,batch_id) VALUES(?,?,?,?,?,?,?,?)',
                (product_id,location_id,target,qty,holder,due_date,reference,batch_id)).lastrowid
            self._audit(db,actor,'returnable_lent',lid,{'qty':qty})
            return self._done(db,token,payload,lid)

    def return_loan(self, loan_id, qty, *, actor, token):
        qty=scaled(qty); payload=['return_loan',loan_id,qty]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            loan=db.execute('SELECT * FROM loans WHERE id=?',(loan_id,)).fetchone()
            if not loan or qty<=0 or qty>loan['qty']-loan['returned']:raise ValidationError('Return exceeds outstanding quantity or is zero.')
            mid=self._movement(db,loan['product_id'],-qty,'loan_out','Returnable returned',loan['reference'],actor,location_id=loan['holder_location'],batch_id=loan['batch_id'])
            cost=-db.execute('SELECT value_delta FROM movements WHERE id=?',(mid,)).fetchone()[0]
            self._movement(db,loan['product_id'],qty,'loan_in','Returnable returned',loan['reference'],actor,location_id=loan['location_id'],batch_id=loan['batch_id'],total_cost=cost)
            db.execute('UPDATE loans SET returned=returned+? WHERE id=?',(qty,loan_id))
            self._audit(db,actor,'returnable_received',loan_id,{'qty':qty})
            return self._done(db,token,payload,qty)
