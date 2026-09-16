"""Work orders, material WIP, recovery accounting and time-phased material planning."""
from datetime import date
import json

from inventory import ValidationError, amount, quantity, scaled, text, line_value
from inventory_ops import day, rounded


def requirement(per_unit, output):
    value,remainder=divmod(per_unit*output,1000)
    if remainder:raise ValidationError('This recipe requires more than three decimal places. Adjust the production quantity.')
    if value>10**12:raise ValidationError('Material requirement exceeds the supported quantity range.')
    return value


class Production:
    @staticmethod
    def _work(db, work_id, writable=False):
        w=db.execute('SELECT * FROM work_orders WHERE id=?',(work_id,)).fetchone()
        if not w:raise ValidationError('Choose a work order.')
        if writable and w['state'] in ('completed','cancelled'):raise ValidationError('This work order is closed.')
        return dict(w)

    def create_work_order(self, product_id, qty, location_id, operator, due_date, stages, notes='', planned_overhead='0', order_line_id=None, *, actor, token):
        qty=scaled(qty); due_date=day(due_date)
        operator=text(operator,'Assigned operator',required=True,limit=100)
        stages=[text(s,'Stage',required=True,limit=80) for s in stages]
        notes=text(notes,'Notes',limit=1000); overhead=scaled(planned_overhead,'Planned overhead',100)
        if qty<=0 or not 1<=len(stages)<=15 or len(set(stages))!=len(stages):
            raise ValidationError('Use a positive planned quantity and 1–15 distinct production stages.')
        payload=['work_order',product_id,qty,location_id,operator,due_date,stages,notes,overhead,order_line_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            self._product(db,product_id); self._location(db,location_id)
            recipe=db.execute('SELECT r.*,p.unit_price FROM recipes r JOIN products p ON p.id=r.component_id WHERE r.product_id=?',(product_id,)).fetchall()
            if not recipe:raise ValidationError('Save a bill of materials for this finished product first.')
            if order_line_id is not None:
                line=db.execute("SELECT l.* FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id WHERE l.id=? AND o.state IN ('confirmed','partial')",(order_line_id,)).fetchone()
                if not line or line['product_id']!=product_id:raise ValidationError('Choose an open sales order line for this product.')
                allocated=db.execute("SELECT COALESCE(SUM(planned),0) FROM work_orders WHERE order_line_id=? AND state<>'cancelled'",(order_line_id,)).fetchone()[0]
                if qty>line['qty']-allocated:raise ValidationError('Planned production exceeds the order quantity not already assigned to work orders.')
            wid=db.execute("""INSERT INTO work_orders(product_id,order_line_id,location_id,planned,operator,due_date,stages,notes,planned_overhead,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))""",(product_id,order_line_id,location_id,qty,operator,due_date,json.dumps(stages),notes,overhead)).lastrowid
            db.execute('UPDATE work_orders SET number=? WHERE id=?',(f'WO-{wid:06d}',wid))
            db.executemany('INSERT INTO work_material_plan VALUES(?,?,?,?,?)',[(wid,r['component_id'],r['qty'],requirement(r['qty'],qty),r['unit_price']) for r in recipe])
            self._audit(db,actor,'work_order_created',wid,{'planned':qty,'operator':operator,'recipe_snapshot':True})
            return self._done(db,token,payload,wid)

    def work_orders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT w.*,p.item_name,p.item_code,p.unit,l.name location
                FROM work_orders w JOIN products p ON p.id=w.product_id JOIN locations l ON l.id=w.location_id ORDER BY w.id DESC''')]

    def advance_work_order(self, work_id, stage_index, operator, due_date, note, *, actor):
        operator=text(operator,'Assigned operator',required=True,limit=100); due_date=day(due_date)
        note=text(note,'Progress note',required=True,limit=1000)
        with self.connect(True) as db:
            w=self._work(db,work_id,True); stages=json.loads(w['stages'])
            if stage_index not in (w['stage_index'],w['stage_index']+1) or stage_index>=len(stages):
                raise ValidationError('Keep the current stage or advance to the next stage.')
            state='released' if w['state']=='planned' else 'in_progress'
            db.execute('UPDATE work_orders SET stage_index=?,operator=?,due_date=?,state=? WHERE id=?',(stage_index,operator,due_date,state,work_id))
            self._audit(db,actor,'work_progress',work_id,{'stage':stages[stage_index],'operator':operator,'due_date':due_date,'previous_due_date':w['due_date'],'note':note})

    def issue_work_materials(self, work_id, quantities, *, actor, token):
        quantities={int(k):scaled(v) for k,v in quantities.items()}
        payload=['work_materials',work_id,quantities]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            w=self._work(db,work_id,True)
            if w['state']=='planned':raise ValidationError('Release the work order before issuing materials.')
            if not any(quantities.values()):raise ValidationError('Enter material quantities to consume into work in progress.')
            for pid,qty in quantities.items():
                if not db.execute('SELECT 1 FROM work_material_plan WHERE work_id=? AND product_id=?',(work_id,pid)).fetchone():
                    raise ValidationError('Material is not part of this work order recipe.')
                if not qty:continue
                mids=self._take(db,pid,qty,w['location_id'],'work_consumption','Material consumed into WIP',w['number'],actor)
                db.executemany('INSERT INTO work_material_usage(work_id,movement_id) VALUES(?,?)',[(work_id,mid) for mid in mids])
            db.execute("UPDATE work_orders SET state='in_progress' WHERE id=?",(work_id,))
            self._audit(db,actor,'work_materials_consumed',work_id,quantities)
            return self._done(db,token,payload,work_id)

    def record_work_cost(self, work_id, kind, hours, rate, note, *, actor, token):
        if kind not in ('labour','machine','overhead'):raise ValidationError('Choose labour, machine or overhead.')
        hours=scaled(hours,'Hours'); rate=scaled(rate,'Hourly rate / overhead amount',100)
        note=text(note,'Cost description',required=True,limit=500)
        cost=rate if kind=='overhead' else line_value(hours,rate)
        if cost<=0:raise ValidationError('Enter a positive cost.')
        payload=['work_cost',work_id,kind,hours,rate,note]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            w=self._work(db,work_id,True)
            if w['state']=='planned':raise ValidationError('Release the work order before recording actual costs.')
            cid=db.execute("INSERT INTO work_costs(work_id,kind,hours,rate,cost,note,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",(work_id,kind,hours,rate,cost,note)).lastrowid
            self._audit(db,actor,'work_cost_recorded',work_id,{'kind':kind,'cost':cost})
            return self._done(db,token,payload,cid)

    @staticmethod
    def _work_totals(db, work_id):
        material=db.execute('SELECT COALESCE(-SUM(m.value_delta),0) FROM work_material_usage u JOIN movements m ON m.id=u.movement_id WHERE u.work_id=?',(work_id,)).fetchone()[0]
        costs={r['kind']:r['total'] for r in db.execute('SELECT kind,SUM(cost) total FROM work_costs WHERE work_id=? GROUP BY kind',(work_id,))}
        recovery=db.execute('SELECT COALESCE(SUM(recovery_value),0) FROM work_scrap WHERE work_id=?',(work_id,)).fetchone()[0]
        allocated=db.execute('SELECT COALESCE(SUM(m.value_delta),0) FROM work_outputs o JOIN movements m ON m.id=o.movement_id WHERE o.work_id=?',(work_id,)).fetchone()[0]
        total=material+sum(costs.values())-recovery
        return dict(material=material,labour=costs.get('labour',0),machine=costs.get('machine',0),overhead=costs.get('overhead',0),recovery=recovery,total=total,output_value=allocated,wip_value=total-allocated)

    def record_work_scrap(self, work_id, product_id, qty, reason, recovered_product_id=None, recovered_qty='0', recovery_value='0', batch_id=None, *, actor, token):
        qty=scaled(qty); recovered_qty=scaled(recovered_qty,'Recovered quantity'); recovery_value=scaled(recovery_value,'Recovery value',100)
        reason=text(reason,'Scrap reason',required=True,limit=500)
        payload=['work_scrap',work_id,product_id,qty,reason,recovered_product_id,recovered_qty,recovery_value,batch_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            w=self._work(db,work_id,True)
            issued=db.execute('SELECT COALESCE(-SUM(m.delta),0) FROM work_material_usage u JOIN movements m ON m.id=u.movement_id WHERE u.work_id=? AND m.product_id=?',(work_id,product_id)).fetchone()[0]
            scrap=db.execute('SELECT COALESCE(SUM(qty),0) FROM work_scrap WHERE work_id=? AND product_id=?',(work_id,product_id)).fetchone()[0]
            if qty<=0 or qty>issued-scrap:raise ValidationError('Scrap must be part of material already consumed by this work order.')
            if bool(recovered_product_id)!=bool(recovered_qty) or (recovery_value and not recovered_qty):
                raise ValidationError('Choose a recovery product and positive recovery quantity together.')
            if recovered_product_id==product_id and recovered_qty>qty:
                raise ValidationError('Recovered quantity cannot exceed scrap quantity for the same product.')
            totals=self._work_totals(db,work_id)
            if recovery_value>totals['wip_value']:raise ValidationError('Recovery value cannot exceed unallocated work in progress cost.')
            mid=None
            if recovered_qty:
                mid=self._movement(db,recovered_product_id,recovered_qty,'offcut_recovery','Recoverable production offcuts',w['number'],actor,
                    location_id=w['location_id'],batch_id=batch_id,total_cost=recovery_value)
            sid=db.execute("""INSERT INTO work_scrap(work_id,product_id,qty,reason,recovered_product_id,recovered_qty,recovery_value,movement_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now'))""",(work_id,product_id,qty,reason,recovered_product_id,recovered_qty,recovery_value,mid)).lastrowid
            self._audit(db,actor,'work_scrap_recorded',work_id,{'quantity':qty,'recovered':recovered_qty,'value':recovery_value})
            return self._done(db,token,payload,sid)

    def complete_work_output(self, work_id, qty, batch_id=None, variance_note='', *, actor, token):
        qty=scaled(qty); note=text(variance_note,'Completion / variance note',limit=1000)
        payload=['work_output',work_id,qty,batch_id,note]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            w=self._work(db,work_id,True)
            if w['state']=='planned' or qty<=0 or qty>w['planned']-w['completed']:
                raise ValidationError('Release this work order and enter output within its remaining planned quantity.')
            if not db.execute('SELECT 1 FROM work_material_usage WHERE work_id=?',(work_id,)).fetchone():
                raise ValidationError('Record materials consumed before reporting finished output.')
            for r in db.execute('SELECT * FROM work_material_plan WHERE work_id=?',(work_id,)):
                used=db.execute('SELECT COALESCE(-SUM(m.delta),0) FROM work_material_usage u JOIN movements m ON m.id=u.movement_id WHERE u.work_id=? AND m.product_id=?',(work_id,r['product_id'])).fetchone()[0]
                lost=db.execute('SELECT COALESCE(SUM(qty),0) FROM work_scrap WHERE work_id=? AND product_id=?',(work_id,r['product_id'])).fetchone()[0]
                if used-lost<requirement(r['per_unit'],w['completed']+qty) and not note:
                    raise ValidationError('Net material consumption is below the recipe. Explain the variance before completing output.')
            totals=self._work_totals(db,work_id)
            value=rounded(totals['wip_value']*qty,w['planned']-w['completed'])
            mid=self._movement(db,w['product_id'],qty,'work_output','Completed work order output',w['number'],actor,
                location_id=w['location_id'],batch_id=batch_id,total_cost=value)
            db.execute('INSERT INTO work_outputs(work_id,movement_id,note) VALUES(?,?,?)',(work_id,mid,note))
            complete=w['completed']+qty==w['planned']
            db.execute('UPDATE work_orders SET completed=completed+?,state=?,stage_index=? WHERE id=?',
                (qty,'completed' if complete else 'in_progress',len(json.loads(w['stages']))-1 if complete else w['stage_index'],work_id))
            # Every new work-order output is held until a final quality inspection releases it.
            self._open_inspection(db,w['product_id'],w['location_id'],batch_id,qty,'final',w['number'],actor,work_id)
            self._audit(db,actor,'work_output_completed',work_id,{'qty':qty,'allocated_cost':value,'note':note,'quality_hold':True})
            return self._done(db,token,payload,mid)

    def cancel_work_order(self, work_id, reason, *, actor):
        reason=text(reason,'Cancellation reason',required=True,limit=500)
        with self.connect(True) as db:
            self._work(db,work_id,True)
            if any(db.execute(f'SELECT 1 FROM {table} WHERE work_id=?',(work_id,)).fetchone() for table in ('work_material_usage','work_costs','work_outputs')):
                raise ValidationError('A work order with actual materials, costs or output cannot be cancelled.')
            db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?",(work_id,))
            self._audit(db,actor,'work_order_cancelled',work_id,{'reason':reason})

    def work_order_detail(self, work_id):
        with self.connect() as db:
            w=self._work(db,work_id); w.update(self._work_totals(db,work_id))
            w['materials']=[dict(r) for r in db.execute('''SELECT p.*,s.item_name,s.item_code,s.unit,
                COALESCE((SELECT -SUM(m.delta) FROM work_material_usage u JOIN movements m ON m.id=u.movement_id WHERE u.work_id=p.work_id AND m.product_id=p.product_id),0) actual,
                COALESCE((SELECT SUM(qty) FROM work_scrap WHERE work_id=p.work_id AND product_id=p.product_id),0) scrap
                FROM work_material_plan p JOIN products s ON s.id=p.product_id WHERE p.work_id=?''',(work_id,))]
            w['costs']=[dict(r) for r in db.execute('SELECT * FROM work_costs WHERE work_id=?',(work_id,))]
            w['scrap_records']=[dict(r) for r in db.execute('SELECT * FROM work_scrap WHERE work_id=?',(work_id,))]
            w['planned_cost']=sum(line_value(r['planned_qty'],r['price']) for r in w['materials'])+w['planned_overhead']
            w['unit_output_cost']=rounded(w['output_value']*1000,w['completed']) if w['completed'] else 0
            line=db.execute('SELECT price FROM sales_order_lines WHERE id=?',(w['order_line_id'],)).fetchone()
            w['committed_net_revenue']=line_value(w['planned'],line['price']) if line else None
            return w

    def material_plan(self, horizon):
        """Net chronological demands once against shared stock, dated POs and scheduled WO output.

        Existing WOs supply finished goods and independently demand their unissued snapshotted
        components. Only uncovered make demand explodes the current recipe, avoiding double count.
        """
        horizon=day(horizon)
        with self.connect() as db:
            products={r['id']:dict(r) for r in db.execute('SELECT * FROM products')}
            available={pid:max(0,self._available_internal(db,pid)) for pid in products}
            supplies={pid:[] for pid in products}; undated={pid:0 for pid in products}
            for r in db.execute("SELECT l.product_id,l.qty-l.received qty,o.due_date FROM po_lines l JOIN purchase_orders o ON o.id=l.po_id WHERE o.state IN ('sent','partial') AND l.qty>l.received"):
                if r['due_date']:supplies[r['product_id']].append([r['due_date'],r['qty'],'purchase'])
                else:undated[r['product_id']]+=r['qty']
            demands=[]
            for w in db.execute("SELECT w.* FROM work_orders w JOIN locations l ON l.id=w.location_id WHERE w.state NOT IN ('completed','cancelled') AND l.kind IN ('warehouse','shop')"):
                supplies[w['product_id']].append([w['due_date'],w['planned']-w['completed'],'production'])
            for w in db.execute("SELECT * FROM work_orders WHERE state NOT IN ('completed','cancelled') AND due_date<=?",(horizon,)):
                for r in db.execute('SELECT * FROM work_material_plan WHERE work_id=?',(w['id'],)):
                    issued=db.execute('SELECT COALESCE(-SUM(m.delta),0) FROM work_material_usage u JOIN movements m ON m.id=u.movement_id WHERE u.work_id=? AND m.product_id=?',(w['id'],r['product_id'])).fetchone()[0]
                    if r['planned_qty']>issued:demands.append((w['due_date'],r['product_id'],r['planned_qty']-issued,w['number']))
            for r in db.execute("SELECT l.product_id,l.qty-l.dispatched qty,o.number,o.delivery_date FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id WHERE o.state IN ('confirmed','partial') AND o.delivery_date<=? AND l.qty>l.dispatched",(horizon,)):
                demands.append((r['delivery_date'],r['product_id'],r['qty'],r['number']))
            for entries in supplies.values():entries.sort(key=lambda s:s[0])
            rows=[]
            def net(pid,qty,due,source,path):
                if pid in path:raise ValidationError('A recipe cycle prevents material planning.')
                p=products[pid]; used=min(qty,available[pid]); available[pid]-=used; remaining=qty-used
                purchase=production=0
                for supply in supplies[pid]:
                    if supply[0]>due:continue
                    taken=min(remaining,supply[1]); supply[1]-=taken; remaining-=taken
                    if supply[2]=='purchase':purchase+=taken
                    else:production+=taken
                recipe=db.execute('SELECT * FROM recipes WHERE product_id=?',(pid,)).fetchall()
                rows.append(dict(product_id=pid,item_code=p['item_code'],product=p['item_name'],unit=p['unit'],source=source,
                    due_date=due,gross=qty,from_stock=used,incoming=purchase,scheduled_output=production,shortage=remaining,
                    action='Make' if recipe else 'Buy',undated_incoming=undated[pid],late_incoming=sum(s[1] for s in supplies[pid] if s[0]>due and s[2]=='purchase')))
                if remaining and recipe:
                    for c in recipe:net(c['component_id'],requirement(c['qty'],remaining),due,source+' / '+p['item_code'],path+(pid,))
            for due,pid,qty,source in sorted(demands):net(pid,qty,due,source,())
            return rows
