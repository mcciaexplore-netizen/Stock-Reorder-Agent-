import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import config
from inventory import load_table, validate_table
from stocklist import Stocklist

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(config, 'DATABASE_PATH', Path(self.temp.name)/'test.sqlite3')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.store = Stocklist(config.DATABASE_PATH)

    def app(self):
        if self.store.needs_setup():
            self.store.bootstrap('owner','Owner','correct horse battery staple')
        token=self.store.login('owner','correct horse battery staple')
        app=AppTest.from_file(str(ROOT/'streamlit_app.py'), default_timeout=25)
        app.session_state['auth_token']=token
        return app.run()

    def seed(self):
        records, errors = validate_table(load_table(ROOT/'inventory.xlsx'))
        self.assertFalse(errors)
        self.store.import_products(records, actor='Owner', token='seed')

    def test_empty_workspace_and_all_pages_load(self):
        app = self.app()
        for page in ['Overview','Products','Suppliers','Stock movements','Purchase orders','Import and backup',
                     'Locations and reservations','Tracking and units','Assembly and jobs','Quotations and bills',
                     'Sales and invoices','Documents','Returnables and repairs','Reports','Exceptions','Offline entry','Settings']:
            app.radio(key='page').set_value(page).run()
            self.assertFalse(app.exception, f'{page}: {[e.value for e in app.exception]}')

    def test_sample_import_from_preview(self):
        app = self.app()
        app.radio(key='page').set_value('Import and backup').run()
        next(c for c in app.checkbox if c.label=='Preview the supplied sample inventory').check().run()
        self.assertFalse(app.exception)
        next(c for c in app.checkbox if c.label=='I reviewed the products and opening balances.').check().run()
        next(b for b in app.button if b.label=='Import products').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(self.store.products()), 8)
        app.radio(key='page').set_value('Overview').run()
        self.assertEqual(app.metric[0].value, '8')
        self.assertEqual(app.metric[1].value, '5')

    def test_reorder_approval_manual_placement_and_receipt(self):
        self.seed()
        app = self.app()
        next(b for b in app.button if b.label=='Create reorder draft').click().run()
        self.assertFalse(app.exception)
        app.radio(key='page').set_value('Purchase orders').run()
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label=='Run dry preview').click().run()
        next(c for c in app.checkbox if c.label=='I reviewed the supplier, quantities, prices and order text.').check().run()
        next(b for b in app.button if b.label=='Approve order').click().run()
        self.assertFalse(app.exception)
        next(t for t in app.text_input if t.label=='Supplier confirmation or external order reference').input('Phone confirmation 123')
        next(b for b in app.button if b.label=='Record order placed outside email').click().run()
        self.assertFalse(app.exception)
        received_fields = [t for t in app.text_input if ': received now (' in t.label]
        self.assertTrue(received_fields)
        for t in received_fields:
            t.input('1')
        next(t for t in app.text_input if t.label=='Delivery reference').input('Delivery 123')
        next(b for b in app.button if b.label=='Record goods received').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.store.orders()[0]['state'], 'partial')

    def test_seeded_workspace_all_pages_load(self):
        self.seed()
        app = self.app()
        for page in ['Products','Suppliers','Stock movements','Purchase orders','Import and backup',
                     'Locations and reservations','Tracking and units','Assembly and jobs','Quotations and bills',
                     'Sales and invoices','Documents','Returnables and repairs','Reports','Exceptions','Offline entry','Settings']:
            app.radio(key='page').set_value(page).run()
            self.assertFalse(app.exception, f'{page}: {[e.value for e in app.exception]}')

    def test_physical_count_does_not_overwrite_concurrent_sale(self):
        self.seed()
        app = self.app()
        app.radio(key='page').set_value('Stock movements').run()
        next(s for s in app.selectbox if s.label=='Movement type').select('stock_count').run()
        pid = self.store.products()[0]['id']
        before = self.store.products()[0]['stock']
        next(t for t in app.text_input if t.label=='Counted stock').input('4')
        next(t for t in app.text_input if t.label=='Reason').input('Shelf count')
        self.store.move_stock(pid, 'sale', '1', 'Concurrent sale', actor='Other operator', token='concurrent')
        next(b for b in app.button if b.label=='Record movement').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Stock changed' in e.value for e in app.error))
        self.assertEqual(self.store.products()[0]['stock'], before-1000)

    def test_owner_setup_and_login_gate(self):
        app=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=60).run()
        self.assertEqual(app.title[0].value,'Set up Stocklist')
        next(t for t in app.text_input if t.label=='Owner username').input('factory')
        next(t for t in app.text_input if t.label=='Your name').input('Factory owner')
        next(t for t in app.text_input if t.label.startswith('Password (')).input('Long factory password 123')
        next(t for t in app.text_input if t.label=='Confirm password').input('Long factory password 123')
        next(b for b in app.button if b.label=='Create owner account').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(t.value=='Inventory overview' for t in app.title))
        next(b for b in app.button if b.label=='Sign out').click().run()
        self.assertEqual(app.title[0].value,'Sign in to Stocklist')
        self.assertFalse(app.dataframe)

    def test_production_form_posts_components_and_output(self):
        self.seed()
        raw=self.store.products()[0]
        output=self.store.save_product(dict(item_code='OUTPUT',item_name='Finished frame',unit='Pcs',unit_price='0',selling_price='100',reorder_level='0',reorder_qty='0'),actor='Owner',token='output')
        self.store.save_recipe(output,[{'product_id':raw['id'],'qty':'1'}],actor='Owner')
        app=self.app()
        app.radio(key='page').set_value('Assembly and jobs').run()
        next(s for s in app.selectbox if s.label=='Finished product / kit').select(output).run()
        next(t for t in app.text_input if t.label=='Finished quantity').input('1')
        next(t for t in app.text_input if t.label=='Assembly job / batch reference').input('WO-UI')
        next(b for b in app.button if b.label=='Record assembly').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(next(p['stock'] for p in self.store.products() if p['id']==output),1000)
        self.assertEqual(next(p['stock'] for p in self.store.products() if p['id']==raw['id']),raw['stock']-1000)

    def test_sales_invoice_form_dispatches_stock(self):
        self.seed()
        self.store.save_settings({'business_name':'Factory','business_address':'Address'},actor='Owner')
        customer=self.store.save_customer('Test customer','Address',actor='Owner')
        pid=self.store.products()[0]['id']; before=self.store.products()[0]['stock']
        app=self.app(); app.radio(key='page').set_value('Sales and invoices').run()
        next(m for m in app.multiselect if m.label=='Invoice products').select(pid).run()
        next(c for c in app.checkbox if c.label=='I checked the customer, tax treatment and goods being dispatched.').check()
        next(b for b in app.button if b.label=='Issue invoice and dispatch goods').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(self.store.invoices()),1)
        self.assertEqual(next(p['stock'] for p in self.store.products() if p['id']==pid),before-1000)

    def test_quotation_and_bill_sections_load(self):
        self.seed()
        product=self.store.products()[0]
        oid=self.store.create_po(product['supplier_id'],[{'product_id':product['id'],'qty':'1','price':'10'}],actor='Owner',token='billorder')
        self.store.approve_po(oid,actor='Owner',revision=1)
        self.store.place_manually(oid,'Supplier confirmed',actor='Owner',revision=1)
        app=self.app(); app.radio(key='page').set_value('Quotations and bills').run()
        app.radio(key='purchasing_section').set_value('Supplier bill verification').run()
        self.assertFalse(app.exception)
        next(t for t in app.text_input if t.label=='Supplier invoice number').input('B-UI')
        next(t for t in app.text_input if t.label.endswith('billed quantity')).input('1')
        next(b for b in app.button if b.label=='Save bill for verification').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(self.store.bills()),1)
        next(s for s in app.selectbox if s.label=='Bill action').select('Review or correct existing bill').run()
        self.assertTrue(any('exceeds received' in w.value for w in app.warning))


if __name__ == '__main__':
    unittest.main()
