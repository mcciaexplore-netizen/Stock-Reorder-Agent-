import inspect
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from inventory import ValidationError
from migrations import VERSION
from security import PERMISSIONS
from stocklist import Stocklist


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ops.sqlite3'; self.s=Stocklist(self.path)
        self.actor='Owner'; self.today=date.today().isoformat(); self.due=(date.today()+timedelta(days=10)).isoformat()
        self.raw=self.product('RAW','100','10'); self.fg=self.product('FINISHED','0','30'); self.offcut=self.product('OFFCUT','0','1')
        self.s.save_recipe(self.fg,[{'product_id':self.raw,'qty':'2'}],actor=self.actor)
        self.customer=self.s.save_customer('Customer <one>','Pune',actor=self.actor)
        self.s.save_settings({'business_name':'Factory','business_address':'Pune'},actor=self.actor)

    def product(self,sku,opening,price):
        return self.s.save_product(dict(item_code=sku,item_name=sku,unit='Pcs',unit_price=price,selling_price='50',reorder_level='0',reorder_qty='0'),
            opening=opening,actor=self.actor,token='product-'+sku)

    def quote(self,qty='10',pid=None,token='quote'):
        return self.s.create_customer_quote(self.customer,[dict(product_id=pid or self.fg,qty=qty,price='50',tax_rate='0')],self.due,self.due,actor=self.actor,token=token)

    def order(self,qty='10',pid=None,token='order'):
        q=self.quote(qty,pid,token+'quote')
        return self.s.confirm_customer_quote(q,actor=self.actor,token=token)

    def work(self,qty='10',line=None,token='work'):
        return self.s.create_work_order(self.fg,qty,1,'Operator',self.due,['Cut','Assemble','Inspect'],planned_overhead='50',order_line_id=line,actor=self.actor,token=token)

    def release(self,wid):
        self.s.advance_work_order(wid,0,'Operator',self.due,'Material released to shopfloor',actor=self.actor)

    def stock(self,pid):return next(p['stock'] for p in self.s.products() if p['id']==pid)

    def test_quote_conversion_partial_delivery_invoice_and_credit(self):
        oid=self.order(pid=self.raw); line=self.s.sales_order(oid)['lines'][0]['id']
        before=self.stock(self.raw)
        did=self.s.dispatch_sales_order(oid,{line:'4'},1,'Truck 1',self.today,actor=self.actor,token='dispatch')
        self.assertEqual(did,self.s.dispatch_sales_order(oid,{line:'4'},1,'Truck 1',self.today,actor=self.actor,token='dispatch'))
        self.assertEqual(self.stock(self.raw),before-4000)
        self.assertEqual(self.s.sales_order(oid)['lines'][0]['dispatched'],4000)
        self.assertEqual(next(r['used_30_days'] for r in self.s.reports()['stock'] if r['item_code']=='RAW'),4000)
        iid=self.s.invoice_sales_dispatch(did,self.today,self.due,actor=self.actor,token='invoice')
        self.assertEqual(self.stock(self.raw),before-4000)
        self.assertEqual(next(r['used_30_days'] for r in self.s.reports()['stock'] if r['item_code']=='RAW'),4000)
        self.assertEqual(self.s.invoice_sales_dispatch(did,self.today,self.due,actor=self.actor,token='invoice'),iid)
        with self.assertRaises(ValidationError):self.s.invoice_sales_dispatch(did,self.today,self.due,actor=self.actor,token='invoice-again')
        with self.assertRaises(ValidationError):self.s.dispatch_sales_order(oid,{line:'7'},1,'over',self.today,actor=self.actor,token='over')
        self.s.dispatch_sales_order(oid,{line:'6'},1,'Truck 2',self.today,actor=self.actor,token='dispatch2')
        self.assertEqual(self.s.sales_order(oid)['state'],'fulfilled')
        inv=self.s.invoice(iid)
        self.s.credit_invoice(iid,{inv['lines'][0]['id']:'1'},'Customer return',actor=self.actor,token='credit')
        self.assertEqual(self.stock(self.raw),before-9000)
        self.assertEqual(self.s.sales_order(oid)['state'],'fulfilled')
        self.assertIn(b'Customer &lt;one&gt;',self.s.customer_document('order',oid))

    def test_quote_expiry_atomic_dispatch_and_linked_order_limits(self):
        q=self.quote()
        with self.s.connect(True) as db:db.execute("UPDATE customer_quotes SET valid_until='2020-01-01' WHERE id=?",(q,))
        with self.assertRaises(ValidationError):self.s.confirm_customer_quote(q,actor=self.actor,token='expired')
        oid=self.order(); line=self.s.sales_order(oid)['lines'][0]['id']; before=self.s.movements()
        with self.assertRaises(ValidationError):self.s.dispatch_sales_order(oid,{line:'1'},1,'Empty stock',self.today,actor=self.actor,token='bad')
        self.assertEqual(self.s.movements(),before); self.assertFalse(self.s.sales_dispatches())
        w=self.work(line=line)
        with self.assertRaises(ValidationError):self.work('1',line,'overplanned')
        with self.assertRaises(ValidationError):self.s.cancel_sales_order(oid,'Cancelled',actor=self.actor)
        self.s.cancel_work_order(w,'No longer needed',actor=self.actor)
        self.s.cancel_sales_order(oid,'Cancelled',actor=self.actor)
        self.assertEqual(self.s.sales_order(oid)['state'],'cancelled')

    def test_parallel_dispatch_does_not_overfulfill(self):
        oid=self.order('6',self.raw); lid=self.s.sales_order(oid)['lines'][0]['id']
        def dispatch(i):
            try:return Stocklist(self.path).dispatch_sales_order(oid,{lid:'4'},1,'Truck',self.today,actor=self.actor,token=f'parallel-{i}')
            except ValidationError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(dispatch,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.s.sales_order(oid)['lines'][0]['dispatched'],4000)

    def test_work_wip_partial_output_scrap_cost_and_quality(self):
        wid=self.work(); self.release(wid)
        self.s.issue_work_materials(wid,{self.raw:'22'},actor=self.actor,token='consume')
        self.s.record_work_cost(wid,'labour','2','10','Welding',actor=self.actor,token='labour')
        self.s.record_work_cost(wid,'machine','1','10','Machine time',actor=self.actor,token='machine')
        self.s.record_work_scrap(wid,self.raw,'2','Offcuts',self.offcut,'1','5',actor=self.actor,token='scrap')
        w=self.s.work_order_detail(wid); self.assertEqual(w['wip_value'],24500); self.assertEqual(w['materials'][0]['scrap'],2000)
        self.assertEqual(self.stock(self.raw),78000); self.assertEqual(self.stock(self.offcut),1000)
        self.s.complete_work_output(wid,'4',actor=self.actor,token='output1')
        w=self.s.work_order_detail(wid); self.assertEqual(w['wip_value'],14700); self.assertEqual(w['output_value'],9800)
        with self.assertRaises(ValidationError):self.s.move_stock(self.fg,'sale','1','held',actor=self.actor,token='held')
        qc=self.s.quality_inspections()[0]['id']
        self.s.record_quality_result(qc,'3','1','One weld rejected',actor=self.actor,token='inspection')
        self.s.route_quality_rework(qc,'Reweld',actor=self.actor)
        self.s.record_quality_result(qc,'1','0','Reweld accepted',actor=self.actor,token='reinspection')
        self.s.complete_work_output(wid,'6',actor=self.actor,token='output2')
        self.assertEqual(self.s.work_order_detail(wid)['wip_value'],0)
        self.assertEqual(self.s.work_order_detail(wid)['total'],24500)
        self.assertEqual(self.s.work_order_detail(wid)['state'],'completed')
        with self.assertRaises(ValidationError):self.s.record_work_cost(wid,'overhead','0','1','Late',actor=self.actor,token='latecost')
        with self.assertRaises(ValidationError):self.s.complete_work_output(wid,'1',actor=self.actor,token='extra')
        self.assertEqual(self.s.health()['ledger_balance_errors'],0)

    def test_recipe_snapshot_and_atomic_material_shortage(self):
        wid=self.work(); self.release(wid)
        self.s.save_recipe(self.fg,[dict(product_id=self.raw,qty='3')],actor=self.actor)
        self.assertEqual(self.s.work_order_detail(wid)['materials'][0]['planned_qty'],20000)
        before=self.s.movements()
        with self.assertRaises(ValidationError):self.s.issue_work_materials(wid,{self.raw:'101'},actor=self.actor,token='short')
        self.assertEqual(before,self.s.movements())
        self.s.issue_work_materials(wid,{self.raw:'19'},actor=self.actor,token='under')
        with self.assertRaises(ValidationError):self.s.complete_work_output(wid,'10',actor=self.actor,token='variance')
        self.s.complete_work_output(wid,'10',variance_note='Lighter gauge reduced allowance',actor=self.actor,token='variance-explained')

    def test_quality_blocks_all_issue_routes_and_disposes_only_rejected(self):
        q=self.s.open_quality_inspection(self.raw,1,'95','incoming','GR-1',actor=self.actor,token='hold')
        for kind in ('sale','issue','damage','adjustment','stock_count'):
            with self.assertRaises(ValidationError):
                self.s.move_stock(self.raw,kind,'-6' if kind=='adjustment' else '0' if kind=='stock_count' else '6','held',expected_stock=100000,actor=self.actor,token='held-'+kind)
        with self.assertRaises(ValidationError):self.s.reserve(self.raw,'6',1,'reserved',actor=self.actor,token='reserve')
        with self.assertRaises(ValidationError):self.s.dispose_quality_stock(q,'1','No inspection',actor=self.actor,token='premature')
        self.s.record_quality_result(q,'90','5','Five damaged',actor=self.actor,token='check')
        self.s.dispose_quality_stock(q,'2','Scrapped',actor=self.actor,token='dispose')
        self.assertEqual(self.stock(self.raw),98000); self.assertEqual(self.s.quality_inspections()[0]['held'],3000)
        self.assertEqual(self.s.location_stock(1)[-1]['product_id'] in (self.raw,self.fg,self.offcut),True)

    def test_quality_batch_fefo_skips_held_batches(self):
        self.s.save_product_options(self.fg,'batch',{},'','0',actor=self.actor)
        b1=self.s.save_batch(self.fg,'B1',self.due,actor=self.actor); b2=self.s.save_batch(self.fg,'B2',actor=self.actor)
        for b in (b1,b2):self.s.move_stock(self.fg,'receipt','5','Goods',batch_id=b,actor=self.actor,token=f'receipt{b}')
        self.s.open_quality_inspection(self.fg,1,'5','incoming','GR',b1,actor=self.actor,token='batchhold')
        self.s.move_stock(self.fg,'sale','5','Available batch',actor=self.actor,token='batchsale')
        self.assertEqual({b['id']:b['stock'] for b in self.s.batches(self.fg)},{b1:5000,b2:0})

    def test_mrp_shared_stock_dated_incoming_and_no_work_double_count(self):
        # One hundred raw on hand, of which ten quarantined; demand is 120 raw for 60 finished.
        self.s.open_quality_inspection(self.raw,1,'10','incoming','Held',actor=self.actor,token='hold')
        self.order('30',token='order1'); self.order('30',token='order2')
        supplier=self.s.save_supplier('Supplier',actor=self.actor)
        po=self.s.create_po(supplier,[dict(product_id=self.raw,qty='20',price='10')],actor=self.actor,token='po')
        self.s.approve_po(po,actor=self.actor,revision=1); self.s.place_manually(po,'Confirmed',actor=self.actor,revision=1)
        self.s.set_order_due(po,self.due,actor=self.actor)
        plan=self.s.material_plan(self.due)
        self.assertEqual(sum(r['shortage'] for r in plan if r['product_id']==self.raw),10000)
        self.assertEqual(sum(r['from_stock'] for r in plan if r['product_id']==self.raw),90000)
        self.assertEqual(sum(r['incoming'] for r in plan),20000)
        self.s.set_order_due(po,(date.today()+timedelta(days=11)).isoformat(),actor=self.actor)
        self.assertEqual(sum(r['shortage'] for r in self.s.material_plan(self.due) if r['product_id']==self.raw),30000)
        self.work('60')
        plan=self.s.material_plan(self.due)
        self.assertEqual(sum(r['gross'] for r in plan if r['product_id']==self.raw),120000)
        self.assertEqual(sum(r['shortage'] for r in plan if r['product_id']==self.fg),0)

    def test_multilevel_recipe_nets_intermediate_stock_before_raw_demand(self):
        sub=self.product('SUB','3','20')
        self.s.save_recipe(sub,[dict(product_id=self.raw,qty='2')],actor=self.actor)
        self.s.save_recipe(self.fg,[dict(product_id=sub,qty='2')],actor=self.actor)
        self.order('4')
        plan=self.s.material_plan(self.due)
        subrow=next(r for r in plan if r['product_id']==sub)
        rawrow=next(r for r in plan if r['product_id']==self.raw)
        self.assertEqual(subrow['gross'],8000); self.assertEqual(subrow['shortage'],5000)
        self.assertEqual(rawrow['gross'],10000)

    def test_delivery_invoice_keeps_batch_allocations_and_rejects_forged_lines(self):
        self.s.save_product_options(self.fg,'batch',{},'','0',actor=self.actor)
        for code in ('A','B'):
            bid=self.s.save_batch(self.fg,code,actor=self.actor)
            self.s.move_stock(self.fg,'receipt','2','Receipt',batch_id=bid,actor=self.actor,token='batch-'+code)
        order=self.order('3'); line=self.s.sales_order(order)['lines'][0]['id']
        delivery=self.s.dispatch_sales_order(order,{line:'3'},1,'DN',self.today,actor=self.actor,token='dispatch')
        with self.assertRaises(ValidationError):
            self.s.issue_invoice(self.customer,[dict(product_id=self.fg,qty='2',price='50',tax_rate='0')],1,self.today,self.due,dispatch_id=delivery,actor=self.actor,token='forged')
        invoice=self.s.invoice_sales_dispatch(delivery,self.today,self.due,actor=self.actor,token='invoice')
        self.assertEqual(len(self.s.invoice(invoice)['lines']),2)
        self.assertEqual(self.stock(self.fg),1000)

    def test_operations_sample_can_resume_and_preserve_later_edits(self):
        from demo_data import seed_sample_data
        from demo_operations import seed_operations_demo
        self.s.bootstrap('demo','Demo owner','correct horse battery staple')
        seed_sample_data(self.s)
        with patch.object(self.s,'record_work_cost',side_effect=RuntimeError('Interrupted')):
            with self.assertRaises(RuntimeError):seed_operations_demo(self.s)
        self.assertTrue(seed_operations_demo(self.s))
        before=(self.s.movements(),self.s.sales_orders(),self.s.work_orders(),self.s.jobwork_orders())
        self.assertFalse(seed_operations_demo(self.s))
        self.assertEqual(before,(self.s.movements(),self.s.sales_orders(),self.s.work_orders(),self.s.jobwork_orders()))
        self.assertEqual(self.s.health()['ledger_balance_errors'],0)

    def test_customer_owned_custody_never_changes_company_stock(self):
        before=self.s.location_stock()
        j=self.s.create_jobwork('customer',self.customer,'Outside process',1,self.due,'Customer job',actor=self.actor,token='jw')
        m=self.s.receive_jobwork_material(j,self.raw,'10','Customer DC',actor=self.actor,token='jw_material')
        self.s.reconcile_jobwork(m,'send','8','OUT',actor=self.actor,token='send')
        self.s.reconcile_jobwork(m,'return','5','IN',actor=self.actor,token='return')
        self.s.reconcile_jobwork(m,'consume','2','Usage',actor=self.actor,token='usage')
        self.s.reconcile_jobwork(m,'scrap','1','Scrap',actor=self.actor,token='jwscrap')
        self.s.reconcile_jobwork(m,'customer_return','7','Customer return',actor=self.actor,token='customerreturn')
        self.s.close_jobwork(j,actor=self.actor)
        self.assertEqual(before,self.s.location_stock())
        self.assertEqual(len(self.s.jobwork_challans(j)),6)
        self.assertIn(b'Customer &lt;one&gt;',self.s.jobwork_document(self.s.jobwork_challans(j)[0]['id']))

    def test_company_jobwork_partial_return_cost_and_custody_guard(self):
        j=self.s.create_jobwork('company',None,'Fabricator',1,self.due,'JW',actor=self.actor,token='jw')
        m=self.s.receive_jobwork_material(j,self.raw,'10','OUT',actor=self.actor,token='send')
        holder=self.s.jobwork_orders()[0]['holder_location']
        self.assertEqual(self.stock(self.raw),100000)
        with self.assertRaises(ValidationError):self.s.move_stock(self.raw,'issue','1','Bypass',location_id=holder,actor=self.actor,token='bypass')
        self.s.reconcile_jobwork(m,'return','4','IN',actor=self.actor,token='return')
        with self.assertRaises(ValidationError):self.s.reconcile_jobwork(m,'return','7','Overreturn',actor=self.actor,token='over')
        self.s.reconcile_jobwork(m,'consume','5','Processed',actor=self.actor,token='consume')
        self.s.reconcile_jobwork(m,'scrap','1','Loss',actor=self.actor,token='loss')
        self.s.close_jobwork(j,actor=self.actor)
        self.assertEqual(self.stock(self.raw),94000)
        self.assertEqual(sum(r['value'] for r in self.s.location_stock() if r['product_id']==self.raw),94000)
        self.assertEqual(self.s.health()['ledger_balance_errors'],0)

    def test_incoming_quality_hold_is_atomic_with_purchase_receipt(self):
        sid=self.s.save_supplier('Vendor',actor=self.actor)
        po=self.s.create_po(sid,[dict(product_id=self.fg,qty='5',price='30')],actor=self.actor,token='po')
        self.s.approve_po(po,actor=self.actor,revision=1); self.s.place_manually(po,'Confirmed',actor=self.actor,revision=1)
        lid=self.s.order(po)['lines'][0]['id']
        self.s.receive_po(po,{lid:'5'},reference='GR',quality_hold=True,actor=self.actor,token='receipt')
        self.assertEqual(self.s.quality_inspections()[0]['held'],5000)
        with self.assertRaises(ValidationError):self.s.move_stock(self.fg,'sale','1','Held',actor=self.actor,token='sell')

    def test_new_mutations_have_explicit_roles_and_viewer_is_blocked(self):
        from customer_orders import CustomerOrders
        from production import Production
        from quality import Quality
        from jobwork import Jobwork
        for cls in (CustomerOrders,Production,Quality,Jobwork):
            for name,fn in inspect.getmembers(cls,inspect.isfunction):
                if not name.startswith('_') and 'actor' in inspect.signature(fn).parameters:self.assertIn(name,PERMISSIONS)
        self.s.bootstrap('owner','Owner','correct horse battery staple')
        self.s.save_user('viewer','Viewer','viewer','correct horse battery staple',actor=self.actor)
        viewer=Stocklist(self.path); viewer.login('viewer','correct horse battery staple')
        with self.assertRaises(ValidationError):viewer.create_work_order(self.fg,'1',1,'Op',self.due,['Build'],actor='Spoof',token='badrole')
        with self.assertRaises(ValidationError):viewer.create_customer_quote(self.customer,[],self.due,self.due,actor='Spoof',token='badquote')

    def test_migration_preserves_v2_and_creates_backup(self):
        # Build a true v2 database using the preserved original migrator.
        from stocklist import SCHEMA
        from migrations import _migrate_v2
        path=Path(self.tmp.name)/'legacy.sqlite3'
        with closing(sqlite3.connect(path)) as db:db.executescript(SCHEMA)
        _migrate_v2(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("INSERT INTO products(item_code,item_name,unit,unit_price,selling_price,reorder_level,reorder_qty) VALUES('OLD','Old','Pcs',1,1,0,0)")
            db.commit()
        s=Stocklist(path)
        self.assertEqual(s.products()[0]['item_code'],'OLD')
        self.assertEqual(s.health()['schema_version'],VERSION)
        self.assertEqual(len(list(path.parent.glob('legacy.sqlite3.before-v3-*'))),1)
        Stocklist(path)
        self.assertEqual(len(list(path.parent.glob('legacy.sqlite3.before-v3-*'))),1)


class OperationsUITests(unittest.TestCase):
    def test_partial_delivery_and_invoice_forms_do_not_dispatch_twice(self):
        from streamlit.testing.v1 import AppTest
        import config
        fixture=OperationsTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        s=fixture.s; s.bootstrap('owner','Owner','correct horse battery staple')
        oid=fixture.order('5',fixture.raw)
        with patch.object(config,'DATABASE_PATH',fixture.path),patch.object(config,'DEMO_ACCESS_PATH',None):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=30)
            app.session_state['auth_token']=s.session_token; app.run()
            app.radio(key='page').set_value('Customer orders').run()
            next(e for e in app.text_input if 'dispatch quantity' in e.label).set_value('2')
            next(e for e in app.text_input if e.label=='Delivery / transport reference').set_value('UI delivery')
            next(e for e in app.button if e.label=='Record partial or full delivery').click().run()
            self.assertFalse(app.exception); self.assertEqual(s.sales_order(oid)['lines'][0]['dispatched'],2000)
            next(e for e in app.button if e.label=='Invoice this delivery').click().run()
            self.assertFalse(app.exception); self.assertEqual(len(s.invoices()),1)
            self.assertEqual(fixture.stock(fixture.raw),98000)

    def test_new_pages_empty_and_populated(self):
        from streamlit.testing.v1 import AppTest
        import config
        fixture=OperationsTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        s=fixture.s
        s.bootstrap('owner','Owner','correct horse battery staple')
        pages=['Customer orders','Work orders','Material planning','Quality inspections','Job-work tracking','Production costs']
        with patch.object(config,'DATABASE_PATH',fixture.path), patch.object(config,'DEMO_ACCESS_PATH',None):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=30)
            app.session_state['auth_token']=s.session_token; app.run()
            for page in pages:
                app.radio(key='page').set_value(page).run(); self.assertFalse(app.exception,page)
            oid=fixture.order(); line=s.sales_order(oid)['lines'][0]['id']; wid=fixture.work(line=line); fixture.release(wid)
            s.issue_work_materials(wid,{fixture.raw:'20'},actor='Owner',token='ui-use')
            s.complete_work_output(wid,'2',actor='Owner',token='ui-output')
            j=s.create_jobwork('customer',fixture.customer,'Processor',1,fixture.due,'JW',actor='Owner',token='ui-jw')
            s.receive_jobwork_material(j,fixture.raw,'5','IN',actor='Owner',token='ui-jwm')
            for page in pages:
                app.radio(key='page').set_value(page).run(); self.assertFalse(app.exception,f'{page}: {[e.value for e in app.exception]}')
