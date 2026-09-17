"""Exercise the cloud adapter against SQLite, without external credentials.

These verify application contracts, not the provider's network service.
"""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

import cloud_database
from inventory import ValidationError
from stocklist import Stocklist


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'remote.sqlite3'
        driver = types.SimpleNamespace(
            connect=lambda url: sqlite3.connect(self.path, isolation_level=None),
            Error=sqlite3.Error, IntegrityError=sqlite3.IntegrityError)
        sdk = patch.dict('sys.modules', {'sqlitecloud': driver})
        sdk.start()
        self.addCleanup(sdk.stop)
        env = patch.dict(os.environ, {'STOCKLIST_OWNER_USERNAME': 'owner',
                                     'STOCKLIST_OWNER_PASSWORD': 'correct horse battery staple'})
        env.start()
        self.addCleanup(env.stop)
        self.url = 'sqlitecloud://test.invalid/stocklist?apikey=secret'

    def store(self):
        store = Stocklist(self.url)
        store.login('owner', 'correct horse battery staple')
        return store

    def test_owner_is_provisioned_but_visitor_is_not_signed_in(self):
        store = Stocklist(self.url)
        self.assertIsNone(store.session_token)
        with self.assertRaises(ValidationError):
            store.identity()
        store.login('owner', 'correct horse battery staple')
        self.assertEqual(store.identity()['role'], 'owner')

    def test_missing_owner_credentials_cannot_open_public_setup(self):
        with patch.dict(os.environ, {'STOCKLIST_OWNER_PASSWORD': ''}):
            with self.assertRaisesRegex(ValidationError, 'hosting settings'):
                Stocklist(self.url)

    def test_records_persist_across_instances_and_rollback(self):
        store = self.store()
        supplier = store.save_supplier('Saved supplier', '', actor='Owner')
        product = store.save_product(dict(item_code='CLOUD-1', item_name='Cloud product', unit='Pcs',
            unit_price='12.75', selling_price='18', reorder_level='10', reorder_qty='20'),
            opening='5', supplier_id=supplier, actor='Owner', token='cloud-product')
        other = self.store()
        with other.connect() as db:
            row = db.execute('SELECT * FROM suppliers WHERE id=?', (supplier,)).fetchone()
            self.assertEqual(dict(row)['name'], 'Saved supplier')
            self.assertEqual(row[0], supplier)
            self.assertEqual(db.execute('SELECT SUM(delta) FROM movements WHERE product_id=?', (product,)).fetchone()[0], 5000)
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            with store.connect(True) as db:
                db.execute("INSERT INTO suppliers(name) VALUES('Rolled back')")
                raise RuntimeError('cancel')
        with other.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM suppliers WHERE name='Rolled back'").fetchone())

    def test_backup_restores_schema_records_and_constraints(self):
        store = self.store()
        store.save_supplier('Backup supplier', '', actor='Owner')
        path = Path(self.temp.name) / 'backup.sqlite3'
        path.write_bytes(store.backup())
        restored = Stocklist(path)
        restored.login('owner', 'correct horse battery staple')
        with restored.connect() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIsNotNone(db.execute("SELECT 1 FROM suppliers WHERE name='Backup supplier'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='movements_no_delete'").fetchone())

    def test_cloud_maintenance_does_not_claim_a_local_backup(self):
        store = self.store()
        self.assertIn('database provider', store.run_maintenance(actor='Owner'))

    def test_driver_errors_do_not_expose_credentials(self):
        driver = types.SimpleNamespace(Error=sqlite3.Error, IntegrityError=sqlite3.IntegrityError)
        raw = types.SimpleNamespace(execute=lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError(self.url)))
        db = cloud_database.Connection(raw, driver)
        with self.assertRaises(sqlite3.OperationalError) as raised:
            db.execute('SELECT 1')
        self.assertNotIn('apikey', str(raised.exception))
        self.assertNotIn('secret', str(raised.exception))

    def test_nonempty_unversioned_database_is_not_overwritten(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE existing(value TEXT)')
        with self.assertRaisesRegex(sqlite3.OperationalError, 'empty dedicated'):
            self.store()

    def test_provider_metadata_is_preserved_during_initialization(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE _sqliteai_vector (tblname TEXT, colname TEXT, key TEXT, value ANY, PRIMARY KEY(tblname,colname,key))')
            db.execute("INSERT INTO _sqliteai_vector VALUES('provider','metadata','version','1')")
            db.commit()
        store = self.store()
        with store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT value FROM _sqliteai_vector').fetchone()[0], 1)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='products'").fetchone())

    def test_provider_metadata_does_not_hide_other_existing_tables(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE _sqliteai_vector (value TEXT)')
            db.execute('CREATE TABLE existing (value TEXT)')
            db.execute("INSERT INTO existing VALUES('keep me')")
            db.commit()
        with self.assertRaisesRegex(sqlite3.OperationalError, 'empty dedicated'):
            self.store()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT value FROM existing').fetchone()[0], 'keep me')
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='products'").fetchone())

    def test_failed_commit_is_reported(self):
        driver = types.SimpleNamespace(Error=sqlite3.Error, IntegrityError=sqlite3.IntegrityError)
        def execute(sql, parameters=()):
            if sql == 'COMMIT':
                raise sqlite3.OperationalError('unavailable')
            return None
        db = cloud_database.Connection(types.SimpleNamespace(execute=execute), driver)
        db.execute('BEGIN IMMEDIATE')
        with self.assertRaises(sqlite3.OperationalError):
            db.commit()
        self.assertTrue(db.in_transaction)

    def test_vercel_without_cloud_url_never_creates_local_database(self):
        import config
        from streamlit.testing.v1 import AppTest
        path = Path(self.temp.name) / 'must-not-exist.sqlite3'
        with patch.dict(os.environ, {'VERCEL': '1'}), patch.object(config, 'SQLITE_CLOUD_URL', ''), patch.object(config, 'DATABASE_PATH', path):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py')).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
