import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from unittest.mock import patch

from inventory import ValidationError
from stocklist import Stocklist,SCHEMA
from security import PERMISSIONS
from migrations import VERSION
from offline import entry_sheet


class ExpandedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'stock.sqlite3'; self.s=Stocklist(self.path)
        self.sid=self.s.save_supplier('Steel supplier','steel@example.invalid',lead_days=5,actor='Owner')
        self.p=self.product('STEEL',opening='100',price='10')
        self.out=self.product('FRAME',price='50')
        self.sub=self.s.save_location('Fabricator','subcontractor',actor='Owner')

    def product(self,code,opening='0',price='10'):
        return self.s.save_product({'item_code':code,'item_name':code,'unit':'Pcs','unit_price':price,'selling_price':'100','reorder_level':'10','reorder_qty':'0'},
            opening=opening,supplier_id=self.sid,actor='Owner',token='product-'+code)

    def po(self,qty='10',price='10'):
        oid=self.s.create_po(self.sid,[{'product_id':self.p,'qty':qty,'price':price}],actor='Owner',token='po')
        self.s.approve_po(oid,actor='Owner',revision=1)
        self.s.place_manually(oid,'supplier confirmed',actor='Owner',revision=1)
        return oid,self.s.order(oid)['lines'][0]['id']

    def tax_setup(self):
        self.s.save_settings({'business_name':'Factory','business_address':'Delhi','gstin':'07ABCDE1234F1Z5','state_code':'07'},actor='Owner')
        self.s.save_product_options(self.p,'none',{},'7308','18',actor='Owner')
        return self.s.save_customer('Buyer','Delhi address',state='07',actor='Owner')

    def test_migration_preserves_old_history_and_balances(self):
        path=Path(self.temp.name)/'old.sqlite3'
        db=sqlite3.connect(path); db.executescript(SCHEMA)
        db.execute("INSERT INTO products(item_code,item_name,unit,unit_price,selling_price,reorder_level,reorder_qty) VALUES('OLD','Old','Pcs',250,300,10,20)")
        db.execute("INSERT INTO movements(product_id,delta,kind,reason,actor,created_at) VALUES(1,3000,'opening','original','Owner','2025-01-01')")
        db.commit(); db.close()
        migrated=Stocklist(path)
        self.assertEqual(migrated.products()[0]['stock'],3000)
        self.assertEqual(migrated.location_stock()[0]['value'],750)
        self.assertEqual(migrated.movements()[0]['reason'],'original')
        self.assertEqual(len(list(path.parent.glob('old.sqlite3.before-v2-*'))),1)
        Stocklist(path)
        self.assertEqual(len(list(path.parent.glob('old.sqlite3.before-v2-*'))),1)

    def test_simultaneous_first_open_keeps_schema_consistent(self):
        path=Path(self.temp.name)/'concurrent.sqlite3'
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:Stocklist(path).health(),range(3)))
        for result in results:
            self.assertEqual(result,{'integrity':'ok','foreign_key_errors':0,'ledger_balance_errors':0,'schema_version':VERSION})

    def test_location_transfer_preserves_ownership_and_cost(self):
        self.s.transfer(self.p,'20',1,self.sub,'DC1',actor='Owner',token='transfer')
        self.assertEqual(self.s.products()[1]['stock'] if self.s.products()[1]['id']==self.p else self.s.products()[0]['stock'],100000)
        rows=[r for r in self.s.location_stock() if r['product_id']==self.p]
        self.assertEqual(sum(r['value'] for r in rows),100000)
        self.assertEqual(next(r['qty'] for r in rows if r['location_id']==self.sub),20000)
        self.s.transfer(self.p,'20',1,self.sub,'DC1',actor='Owner',token='transfer')
        self.assertEqual(sum(r['qty'] for r in rows),100000)
        with self.assertRaises(ValidationError):self.s.move_stock(self.p,'issue','21','job',location_id=self.sub,actor='Owner',token='too-many')

    def test_reservations_block_issue_and_fulfill_once(self):
        rid=self.s.reserve(self.p,'90',1,'job',actor='Owner',token='reserve')
        with self.assertRaises(ValidationError):self.s.move_stock(self.p,'sale','11','sold',actor='Owner',token='sale')
        self.s.release_reservation(rid,actor='Owner',fulfill=True)
        self.assertEqual(next(p['stock'] for p in self.s.products() if p['id']==self.p),10000)
        with self.assertRaises(ValidationError):self.s.release_reservation(rid,actor='Owner',fulfill=True)

    def test_unit_conversion_and_precision(self):
        self.s.save_conversion(self.p,'Box','12',actor='Owner')
        self.s.move_stock(self.p,'receipt','2','boxes',unit='Box',actor='Owner',token='boxes')
        self.assertEqual(next(p['stock'] for p in self.s.products() if p['id']==self.p),124000)
        self.s.save_conversion(self.p,'Small','0.125',actor='Owner')
        with self.assertRaises(ValidationError):self.s.move_stock(self.p,'receipt','0.001','bad',unit='Small',actor='Owner',token='tiny')

    def test_batch_fefo_and_expiry(self):
        self.s.save_product_options(self.out,'batch',{},'','0',actor='Owner')
        early=self.s.save_batch(self.out,'EARLY',(date.today()+timedelta(days=2)).isoformat(),actor='Owner')
        late=self.s.save_batch(self.out,'LATE',(date.today()+timedelta(days=20)).isoformat(),actor='Owner')
        expired=self.s.save_batch(self.out,'OLD',(date.today()-timedelta(days=1)).isoformat(),actor='Owner')
        for bid in (late,early,expired):self.s.move_stock(self.out,'receipt','5','batch',batch_id=bid,actor='Owner',token=str(bid))
        self.s.move_stock(self.out,'sale','6','sold',actor='Owner',token='fefo')
        stocks={b['id']:b['stock'] for b in self.s.batches(self.out)}
        self.assertEqual(stocks,{early:0,late:4000,expired:5000})
        with self.assertRaises(ValidationError):self.s.move_stock(self.out,'sale','5','too many fresh',actor='Owner',token='expiry')
        self.s.move_stock(self.out,'damage','5','expired',batch_id=expired,actor='Owner',token='dispose')

    def test_serial_unique_across_locations(self):
        self.s.save_product_options(self.out,'serial',{},'','0',actor='Owner')
        bid=self.s.save_batch(self.out,'SN-1',warranty_until='2030-01-01',actor='Owner')
        self.s.move_stock(self.out,'receipt','1','serial',batch_id=bid,actor='Owner',token='sn')
        with self.assertRaises(ValidationError):self.s.move_stock(self.out,'receipt','1','duplicate',batch_id=bid,location_id=self.sub,actor='Owner',token='dupsn')
        self.s.transfer(self.out,'1',1,self.sub,'send',batch_id=bid,actor='Owner',token='snt')
        self.assertEqual(self.s.batches(self.out,self.sub)[0]['stock'],1000)
        repair=self.s.save_repair(bid,'Customer','Broken weld',actor='Owner',token='repair')
        self.s.close_repair(repair,'Rewelded',actor='Owner')
        self.assertEqual(self.s.repairs()[0]['state'],'closed')

    def test_production_conserves_cost_and_rolls_back_shortage(self):
        self.s.save_recipe(self.out,[{'product_id':self.p,'qty':'2'}],actor='Owner')
        cost=self.s.assemble(self.out,'10',1,'WO1','50',actor='Owner',token='build')
        self.assertEqual(cost,25000)
        self.assertEqual(self.s.assemble(self.out,'10',1,'WO1','50',actor='Owner',token='build'),25000)
        rows={r['product_id']:r for r in self.s.location_stock(1)}
        self.assertEqual(rows[self.out]['value'],25000); self.assertEqual(rows[self.p]['qty'],80000)
        before=self.s.movements()
        with self.assertRaises(ValidationError):self.s.assemble(self.out,'50',1,'WO2',actor='Owner',token='short')
        self.assertEqual(self.s.movements(),before)

    def test_recipe_cycle_rejected(self):
        self.s.save_recipe(self.out,[{'product_id':self.p,'qty':'2'}],actor='Owner')
        with self.assertRaises(ValidationError):self.s.save_recipe(self.p,[{'product_id':self.out,'qty':'1'}],actor='Owner')
        self.assertFalse(self.s.recipes(self.p))

    def test_job_cost_budget_and_returnables(self):
        jid=self.s.save_job('JOB1','Customer','10',actor='Owner')
        self.assertEqual(self.s.consume_job(jid,self.p,'2',1,actor='Owner',token='job'),2000)
        self.assertEqual(self.s.jobs()[0]['material_cost'],2000)
        loan=self.s.lend(self.p,'5',1,'Contractor',(date.today()-timedelta(days=1)).isoformat(),'DC1',actor='Owner',token='lend')
        self.s.return_loan(loan,'2',actor='Owner',token='return')
        self.s.return_loan(loan,'2',actor='Owner',token='return')
        self.assertEqual(self.s.loans()[0]['returned'],2000)
        with self.assertRaises(ValidationError):self.s.return_loan(loan,'4',actor='Owner',token='over')
        self.s.refresh_alerts()
        self.assertTrue({'Job budget','Returnable overdue'} <= {a['category'] for a in self.s.alerts()})

    def test_quotation_comparison_expiry_and_minimum(self):
        qid=self.s.save_quote(self.sid,self.p,'Q1','8','10','25',3,(date.today()+timedelta(days=30)).isoformat(),actor='Owner',token='q')
        quote=self.s.quotes(self.p,'5')[0]; self.assertEqual(quote['comparison_total'],10500)
        with self.assertRaises(ValidationError):self.s.order_quote(qid,'9',actor='Owner',token='small')
        oid=self.s.order_quote(qid,'10',actor='Owner',token='quote-order')
        self.assertEqual(self.s.order(oid)['total'],8000)
        self.assertEqual(self.s.order_quote(qid,'10',actor='Owner',token='quote-order'),oid)
        old=self.s.save_quote(self.sid,self.p,'OLD','1','1','0',3,'2020-01-01',actor='Owner',token='oldq')
        with self.assertRaises(ValidationError):self.s.order_quote(old,'10',actor='Owner',token='expiredq')

    def test_bill_matching_cumulative_and_landed_cost(self):
        oid,lid=self.po(); self.s.receive_po(oid,{lid:'8'},actor='Owner',token='receipt',reference='GR1',freight='8')
        bid=self.s.save_bill(oid,'B1',date.today().isoformat(),[{'po_line_id':lid,'qty':'10','price':'10'}],'10','18',actor='Owner',token='bill')
        self.assertTrue(self.s.bill_match(bid)['issues'])
        with self.assertRaises(ValidationError):self.s.accept_bill(bid,actor='Owner')
        self.s.save_bill(oid,'B1',date.today().isoformat(),[{'po_line_id':lid,'qty':'8','price':'10'}],'8','14.4',actor='Owner',token='fixbill',bill_id=bid)
        self.assertEqual(self.s.bill_match(bid)['lines'][0]['landed_unit_paise'],1100)
        self.s.accept_bill(bid,actor='Owner')
        b2=self.s.save_bill(oid,'B2',date.today().isoformat(),[{'po_line_id':lid,'qty':'1','price':'10'}],actor='Owner',token='bill2')
        with self.assertRaises(ValidationError):self.s.accept_bill(b2,actor='Owner')
        self.assertEqual(next(r['value'] for r in self.s.location_stock(1) if r['product_id']==self.p),108800)

    def test_invoice_taxes_payment_and_partial_credit(self):
        cid=self.tax_setup()
        iid=self.s.issue_invoice(cid,[{'product_id':self.p,'qty':'3','price':'100','tax_rate':'18'}],1,'2026-09-16','2026-10-16',actor='Owner',token='invoice')
        inv=self.s.invoice(iid)
        self.assertEqual((inv['subtotal'],inv['cgst'],inv['sgst'],inv['igst'],inv['total']),(30000,2700,2700,0,35400))
        self.s.record_payment(iid,'100','BANK1',actor='Owner',token='pay')
        lid=inv['lines'][0]['id']
        credit=self.s.credit_invoice(iid,{lid:'1'},'return',actor='Owner',token='credit')
        self.assertEqual(self.s.invoice(credit)['total'],11800)
        with self.assertRaises(ValidationError):self.s.credit_invoice(iid,{lid:'3'},'over',actor='Owner',token='overcredit')
        with self.assertRaises(ValidationError):self.s.record_payment(iid,'200','BANK2',actor='Owner',token='overpay')
        self.assertIn(b'Tax invoice',self.s.invoice_document(iid))
        self.assertIn(b'invoice',self.s.accounting_export())

    def test_fractional_credit_rounding_exhausts_exact_invoice(self):
        cid=self.tax_setup()
        iid=self.s.issue_invoice(cid,[{'product_id':self.p,'qty':'0.003','price':'3.33','tax_rate':'18'}],1,'2026-09-16','2026-10-16','27',actor='Owner',token='tinyinvoice')
        inv=self.s.invoice(iid); lid=inv['lines'][0]['id']
        totals=[]
        for n in range(3):
            credit=self.s.credit_invoice(iid,{lid:'0.001'},'partial',actor='Owner',token=f'credit{n}')
            totals.append(self.s.invoice(credit)['total'])
        self.assertEqual(sum(totals),inv['total'])

    def test_intra_state_tax_halves_round_consistently(self):
        cid=self.tax_setup()
        iid=self.s.issue_invoice(cid,[{'product_id':self.p,'qty':'1','price':'0.06','tax_rate':'18'}],1,'2026-09-16','2026-10-16',actor='Owner',token='tax-halves')
        inv=self.s.invoice(iid)
        self.assertEqual((inv['cgst'],inv['sgst'],inv['total']),(1,1,8))

    def test_batch_split_invoice_and_return_totals_agree(self):
        cid=self.tax_setup()
        self.s.save_product_options(self.out,'batch',{},'7308','18',actor='Owner')
        for n in range(3):
            bid=self.s.save_batch(self.out,f'B{n}',actor='Owner')
            self.s.move_stock(self.out,'receipt','0.001','receipt',batch_id=bid,actor='Owner',token=f'b{n}')
        iid=self.s.issue_invoice(cid,[{'product_id':self.out,'qty':'0.003','price':'3.33','tax_rate':'18'}],1,'2026-09-16','2026-10-16',actor='Owner',token='split')
        inv=self.s.invoice(iid)
        self.assertEqual(sum(l['net']+l['cgst']+l['sgst']+l['igst'] for l in inv['lines']),inv['total'])
        cid=self.s.credit_invoice(iid,{l['id']:'0.001' for l in inv['lines']},'all back',actor='Owner',token='allcredit')
        self.assertEqual(self.s.invoice(cid)['total'],inv['total'])

    def test_restore_with_user_accounts(self):
        import agent
        self.s.bootstrap('owner','Owner','A sufficiently long password')
        self.s.login('owner','A sufficiently long password')
        backup=Path(self.temp.name)/'snapshot.sqlite3'; backup.write_bytes(self.s.backup())
        self.s.move_stock(self.p,'issue','1','used',actor='Owner',token='later')
        agent.restore_backup(backup,self.path)
        restored=Stocklist(self.path); restored.login('owner','A sufficiently long password')
        self.assertEqual(next(p['stock'] for p in restored.products() if p['id']==self.p),100000)

    def test_invoice_atomic_on_insufficient_stock(self):
        cid=self.tax_setup(); before=self.s.movements()
        with self.assertRaises(ValidationError):self.s.issue_invoice(cid,[{'product_id':self.p,'qty':'101','price':'100'}],1,'2026-09-16','2026-09-16',actor='Owner',token='oversell')
        self.assertFalse(self.s.invoices()); self.assertEqual(self.s.movements(),before)

    def test_attachments_backup_and_type_validation(self):
        aid=self.s.add_attachment('product',self.p,'../../drawing.txt',b'Part number ABC',actor='Owner')
        self.assertEqual(self.s.attachments('product',self.p)[0]['filename'],'drawing.txt')
        self.assertEqual(self.s.add_attachment('product',self.p,'drawing.txt',b'Part number ABC',actor='Owner'),aid)
        with self.assertRaises(ValidationError):self.s.add_attachment('product',self.p,'fake.pdf',b'not pdf',actor='Owner')
        with self.assertRaises(ValidationError):self.s.add_attachment('bad_table',self.p,'drawing.txt',b'no',actor='Owner')
        restore=Path(self.temp.name)/'restored.sqlite3'; restore.write_bytes(self.s.backup())
        self.assertEqual(Stocklist(restore).attachment_content(aid),b'Part number ABC')

    def test_offline_queue_is_idempotent_and_conflicts_visible(self):
        row={'id':'client1','workspace_id':self.s.settings()['workspace_id'],'sku':'STEEL','location':'Main warehouse','kind':'issue','quantity':'2','reason':'job','reference':'J1'}
        self.assertEqual(self.s.sync_movements([row],actor='Owner')[0]['status'],'applied')
        self.assertEqual(self.s.sync_movements([row],actor='Owner')[0]['status'],'applied')
        self.assertEqual(self.s.sync_movements([dict(row,quantity='3')],actor='Owner')[0]['status'],'needs review')
        self.assertEqual(next(p['stock'] for p in self.s.products() if p['id']==self.p),98000)
        self.assertEqual(self.s.sync_movements([dict(row,id='foreign',workspace_id='another-business')],actor='Owner')[0]['status'],'needs review')
        self.assertNotIn(b'__STOCKLIST_DATA__',entry_sheet(self.s.products(),self.s.locations(),self.s.settings()['workspace_id']))

    def test_maintenance_snapshots_and_alert_resolution(self):
        self.s.save_settings({'backup_enabled':'true','backup_days':'1'},actor='Owner')
        self.s.run_maintenance(actor='Owner'); self.s.run_maintenance(actor='Owner')
        self.assertEqual(len(list((self.path.parent/'backups').glob('*.sqlite3'))),1)
        alert=next(a for a in self.s.alerts() if a['key']==f'stock:{self.out}')
        self.s.acknowledge_alert(alert['key'],actor='Owner')
        self.s.move_stock(self.out,'receipt','20','delivery',actor='Owner',token='replenish')
        self.s.refresh_alerts()
        self.assertNotIn(alert['key'],{a['key'] for a in self.s.alerts()})

    def test_purchase_budget_and_pack_rules(self):
        self.s.save_settings({'monthly_budget':'50'},actor='Owner')
        oid=self.s.create_po(self.sid,[{'product_id':self.p,'qty':'10','price':'10'}],actor='Owner',token='budgetpo')
        with self.assertRaises(ValidationError):self.s.approve_po(oid,actor='Owner',revision=1)
        self.s.save_product_options(self.out,'none',{},'','0','20','12',actor='Owner')
        r=next(r for r in self.s.recommendations() if r['id']==self.out)
        self.assertEqual(r['suggested_qty'],24000)

    def test_external_reservations_do_not_reduce_internal_stock_twice(self):
        self.s.transfer(self.p,'90',1,self.sub,'Outside',actor='Owner',token='outside')
        self.s.reserve(self.p,'90',self.sub,'Job',actor='Owner',token='external_reservation')
        self.assertNotIn(self.p,{r['id'] for r in self.s.recommendations()})

    def test_expired_stock_does_not_cover_replenishment(self):
        self.s.save_product_options(self.out,'batch',{},'','0',actor='Owner')
        batch=self.s.save_batch(self.out,'Expired','2020-01-01',actor='Owner')
        self.s.move_stock(self.out,'receipt','20','Old stock',batch_id=batch,actor='Owner',token='expired')
        recommendation=next(r for r in self.s.recommendations() if r['id']==self.out)
        self.assertEqual(recommendation['available'],0)
        with self.assertRaises(ValidationError):self.s.reserve(self.out,'1',1,'Reserve old stock',actor='Owner',token='old_reserve')

    def test_cancelled_order_keeps_received_cost_in_budget(self):
        oid,lid=self.po('10','10')
        self.s.receive_po(oid,{lid:'8'},actor='Owner',token='receive',reference='DN')
        self.s.cancel_po(oid,'Remainder cancelled',actor='Owner')
        self.s.save_settings({'monthly_budget':'100'},actor='Owner')
        new=self.s.create_po(self.sid,[{'product_id':self.p,'qty':'3','price':'10'}],actor='Owner',token='new')
        with self.assertRaises(ValidationError):self.s.approve_po(new,actor='Owner',revision=1)

    def test_role_checks_actor_spoofing_and_revocation(self):
        self.s.bootstrap('owner','Real owner','A sufficiently long password')
        owner_token=self.s.login('owner','A sufficiently long password')
        uid=self.s.save_user('warehouse','Worker','warehouse','Another long password',actor='spoof')
        viewer=self.s.save_user('viewer','Viewer','viewer','Another long password',actor='Owner')
        with self.assertRaises(ValidationError):Stocklist(self.path).products()
        worker=Stocklist(self.path); worker.login('warehouse','Another long password')
        worker.move_stock(self.p,'issue','1','job',actor='Pretend owner',token='work')
        self.assertEqual(worker.movements()[0]['actor'],'Worker')
        with self.assertRaises(ValidationError):worker.save_settings({'monthly_budget':'1'},actor='Owner')
        read=Stocklist(self.path); read.login('viewer','Another long password')
        self.assertTrue(read.products())
        with self.assertRaises(ValidationError):read.move_stock(self.p,'sale','1','bad',actor='Owner',token='viewer')
        with self.assertRaises(ValidationError):read.backup()
        self.s.save_user('warehouse','Worker','warehouse',active=False,user_id=uid,actor='Owner')
        with self.assertRaises(ValidationError):worker.products()
        with self.assertRaises(ValidationError):self.s.save_user('owner','Real owner','viewer',user_id=1,actor='Owner')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE sessions SET expires=0')
        db.close()
        with self.assertRaises(ValidationError):self.s.products()

    def test_login_rate_limit_persists_failures(self):
        self.s.bootstrap('owner','Owner','A sufficiently long password')
        for _ in range(5):
            with self.assertRaises(ValidationError):self.s.login('owner','wrong password value')
        with self.assertRaisesRegex(ValidationError,'Too many'):self.s.login('owner','A sufficiently long password')
        with patch('security.time.time',return_value=time.time()+901):
            self.assertTrue(self.s.login('owner','A sufficiently long password'))


if __name__=='__main__':unittest.main()
