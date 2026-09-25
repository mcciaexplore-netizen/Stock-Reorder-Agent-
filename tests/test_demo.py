import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import config
from demo_access import demo_profiles, write_demo_access
from demo_data import seed_sample_data
from inventory import ValidationError
from stocklist import Stocklist

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'Disposable demo test password 123'


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'demo.sqlite3'
        self.access = Path(self.temp.name) / 'demo-access.json'
        self.store = Stocklist(self.path)
        self.store.bootstrap('demo', 'Demo owner', PASSWORD)

    def provision(self):
        write_demo_access(self.store, self.access, 'demo', PASSWORD)
        return demo_profiles(self.path, self.access)

    def snapshot(self):
        with self.store.connect() as db:
            return {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                    for table in ('products', 'movements', 'purchase_orders', 'po_lines', 'invoices',
                                  'payments', 'jobs', 'job_usage', 'batches', 'bills', 'loans', 'repairs')}

    def test_sample_workflows_preserve_existing_data_and_later_edits(self):
        original = self.store.save_product(dict(item_code='ORIGINAL', item_name='Existing product', unit='Pcs',
            unit_price='10', selling_price='20', reorder_level='0', reorder_qty='0'),
            opening='9', actor='Owner', token='original')
        self.assertTrue(seed_sample_data(self.store))
        self.assertEqual(len(self.store.products()), 13)
        self.assertEqual({o['state'] for o in self.store.orders()}, {'draft', 'sent', 'partial', 'received'})
        self.assertEqual({b['state'] for b in self.store.bills()}, {'review', 'accepted'})
        self.assertEqual(len(self.store.invoices()), 4)
        self.assertEqual(len(self.store.jobs()), 3)
        self.assertTrue(any(i['paid'] and i['paid'] < i['total'] for i in self.store.invoices()))
        self.assertTrue(any(j['material_cost'] > j['budget'] for j in self.store.jobs()))
        self.assertEqual(next(p['stock'] for p in self.store.products() if p['id'] == original), 9000)
        self.store.move_stock(original, 'issue', '1', 'Later edit', actor='Owner', token='later')
        before = self.snapshot()
        self.assertFalse(seed_sample_data(self.store))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.health(), dict(integrity='ok', foreign_key_errors=0,
                                                ledger_balance_errors=0, schema_version=3))

    def test_interrupted_load_can_resume_without_duplicate_transactions(self):
        with patch.object(self.store, 'save_bill', side_effect=RuntimeError('Interrupted')):
            with self.assertRaises(RuntimeError):
                seed_sample_data(self.store)
        with self.store.connect() as db:
            before = [tuple(r) for r in db.execute('SELECT id,delta,value_delta FROM movements')]
        self.assertTrue(seed_sample_data(self.store))
        with self.store.connect() as db:
            after = [tuple(r) for r in db.execute('SELECT id,delta,value_delta FROM movements')]
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(len(self.store.products()), 12)
        self.assertEqual(len(self.store.orders()), 4)
        self.assertEqual(len(self.store.jobs()), 3)
        self.assertEqual(len(self.store.batches()), 5)
        self.assertEqual(self.store.health()['ledger_balance_errors'], 0)

    def test_access_is_explicit_and_bound_to_original_workspace(self):
        self.assertEqual(demo_profiles(self.path, ''), [])
        self.assertEqual(demo_profiles(self.path, self.access), [])
        self.assertEqual(len(self.provision()), 4)
        saved = self.access.read_text(encoding='utf-8')
        write_demo_access(self.store, self.access, 'demo', PASSWORD)
        self.assertEqual(self.access.read_text(encoding='utf-8'), saved)
        other = Path(self.temp.name) / 'business.sqlite3'
        Stocklist(other)
        self.assertEqual(demo_profiles(other, self.access), [])
        with self.store.connect(True) as db:
            db.execute("UPDATE settings SET value='different-workspace' WHERE key='workspace_id'")
        self.assertEqual(demo_profiles(self.path, self.access), [])
        self.access.write_text('{bad json', encoding='utf-8')
        self.assertEqual(demo_profiles(self.path, self.access), [])

    def test_shortcuts_keep_normal_permissions_and_account_revocation(self):
        profiles = self.provision()
        viewer = next(p for p in profiles if p['role'] == 'viewer')
        viewer_store = Stocklist(self.path)
        viewer_store.login(viewer['username'], viewer['password'])
        self.assertEqual(viewer_store.identity()['role'], 'viewer')
        with self.assertRaises(ValidationError):
            viewer_store.save_location('Forbidden', actor='Owner')
        with self.assertRaises(ValidationError):
            seed_sample_data(viewer_store)
        user = next(u for u in self.store.users() if u['username'] == viewer['username'])
        self.store.save_user(user['username'], user['name'], 'viewer', active=False,
                             user_id=user['id'], actor='Owner')
        self.assertNotIn('viewer', [p['role'] for p in demo_profiles(self.path, self.access)])
        with self.assertRaises(ValidationError):
            viewer_store.identity()

    def test_normal_sign_in_has_no_demo_buttons(self):
        self.provision()
        with patch.object(config, 'DATABASE_PATH', self.path), patch.object(config, 'DEMO_ACCESS_PATH', ''):
            app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=60).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, 'Sign in to Stocklist')
            self.assertFalse(any(b.key and b.key.startswith('demo_login_') for b in app.button))

    def test_every_demo_button_signs_in_with_its_role_and_sample_pages_load(self):
        seed_sample_data(self.store)
        profiles = self.provision()
        with patch.object(config, 'DATABASE_PATH', self.path), patch.object(config, 'DEMO_ACCESS_PATH', str(self.access)):
            app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=60).run()
            for profile in profiles:
                app.button(key='demo_login_' + profile['role']).click().run()
                self.assertFalse(app.exception)
                signed_in = Stocklist(self.path, session_token=app.session_state['auth_token'])
                self.assertEqual(signed_in.identity()['role'], profile['role'])
                self.assertTrue(any(t.value == 'Inventory overview' for t in app.title))
                self.assertFalse(any(b.key and b.key.startswith('demo_login_') for b in app.button))
                if profile['role'] == 'owner':
                    for page in ['Products', 'Stock movements', 'Tracking and units', 'Locations and reservations',
                                 'Purchase orders', 'Suppliers', 'Reports', 'Import and backup', 'Settings']:
                        app.radio(key='page').set_value(page).run()
                        self.assertFalse(app.exception, page)

                next(b for b in app.button if b.label == 'Sign out').click().run()
                self.assertEqual(app.title[0].value, 'Sign in to Stocklist')
                self.assertFalse(app.dataframe)
                self.assertFalse(app.radio)


if __name__ == '__main__':
    unittest.main()
