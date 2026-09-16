"""Optional, repeatable samples for the advanced operations screens."""
from datetime import date, timedelta
import json
from inventory import ValidationError


def seed_operations_demo(store):
    identity=store.identity()
    if not identity or identity['role']!='owner':raise ValidationError('Only a demo owner can load sample operations.')
    key='_demo_operations_v1'
    with store.connect(True) as db:
        row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        state=json.loads(row['value']) if row else dict(date=date.today().isoformat(),complete=False)
        if state['complete']:return False
        if not db.execute("SELECT 1 FROM settings WHERE key IN ('_demo_general_business_v1','_demo_manufacturing_v1')").fetchone():
            raise ValidationError('Load the general sample pack first.')
        db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,json.dumps(state)))
    actor='Demo setup'; anchor=date.fromisoformat(state['date'])
    day=lambda n:(anchor+timedelta(days=n)).isoformat(); token=lambda name:'demo-operations-v1:'+name
    p={r['item_code']:r['id'] for r in store.products()}
    customer=next(c['id'] for c in store.customers() if c['name']=='Demo Sahyadri Engineering')
    if 'DEMO-OFFCUT' not in p:
        p['DEMO-OFFCUT']=store.save_product(dict(item_code='DEMO-OFFCUT',item_name='Recoverable steel offcuts',unit='Kg',category='Recovery',unit_price='15',selling_price='20',reorder_level='0',reorder_qty='0'),actor=actor,token=token('offcut-product'))
    q=store.create_customer_quote(customer,[dict(product_id=p['DEMO-RACK'],qty='50',price='2800',tax_rate='0')],day(30),day(10),'Sample customer commitment: staged delivery.',actor=actor,token=token('quote'))
    oid=store.confirm_customer_quote(q,actor=actor,token=token('confirm')); line=store.sales_order(oid)['lines'][0]['id']
    delivery=store.dispatch_sales_order(oid,{line:'2'},1,'DEMO-DN-001',day(0),actor=actor,token=token('delivery'))
    store.invoice_sales_dispatch(delivery,day(0),day(30),actor=actor,token=token('invoice'))
    store.create_customer_quote(customer,[dict(product_id=p['DEMO-BRACKET'],qty='100',price='175',tax_rate='0')],day(20),day(14),'Sample quotation awaiting customer confirmation.',actor=actor,token=token('openquote'))
    wid=store.create_work_order(p['DEMO-RACK'],'3',1,'Demo operator · Assembly',day(7),['Cutting','Welding','Coating','Final inspection'],
        'Sample partial work order with recoverable offcuts.',planned_overhead='600',order_line_id=line,actor=actor,token=token('work'))
    if store.work_order_detail(wid)['state']=='planned':store.advance_work_order(wid,0,'Demo operator · Assembly',day(7),'Released to workshop',actor=actor)
    store.issue_work_materials(wid,{p['DEMO-SHEET']:'19',p['DEMO-BOLT']:'60',p['DEMO-WIRE']:'0.45'},actor=actor,token=token('materials'))
    store.record_work_cost(wid,'labour','3','120','Welding and assembly',actor=actor,token=token('labour'))
    store.record_work_cost(wid,'machine','1.5','80','Cutting machine',actor=actor,token=token('machine'))
    store.record_work_scrap(wid,p['DEMO-SHEET'],'1','Cutting allowance',p['DEMO-OFFCUT'],'0.8','12',actor=actor,token=token('scrap'))
    store.complete_work_output(wid,'1',actor=actor,token=token('output'))
    qc=next(q['id'] for q in store.quality_inspections() if q['work_id']==wid)
    store.record_quality_result(qc,'1','0','Dimensions and welds accepted.',actor=actor,token=token('output-qc'))
    incoming=store.open_quality_inspection(p['DEMO-SHEET'],1,'5','incoming','DEMO-QC-STEEL',actor=actor,token=token('incoming'))
    store.record_quality_result(incoming,'4','1','One kg has surface damage; held for review.',actor=actor,token=token('incoming-result'))
    for owner,product,qty in [('customer',p['DEMO-SHEET'],'25'),('company',p['DEMO-ROD'],'4')]:
        jid=store.create_jobwork(owner,customer if owner=='customer' else None,'Demo precision processor',1,day(-2),'DEMO-JW-'+owner,actor=actor,token=token('jw-'+owner))
        mid=store.receive_jobwork_material(jid,product,qty,'DEMO-CHALLAN-'+owner,actor=actor,token=token('jw-material-'+owner))
        if owner=='customer':store.reconcile_jobwork(mid,'send','20','DEMO-OUT',actor=actor,token=token('jw-send'))
        store.reconcile_jobwork(mid,'return','5' if owner=='customer' else '1','DEMO-PARTIAL-RETURN',actor=actor,token=token('jw-return-'+owner))
    store.refresh_alerts()
    with store.connect(True) as db:
        state['complete']=True; db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(state),key))
    return True
