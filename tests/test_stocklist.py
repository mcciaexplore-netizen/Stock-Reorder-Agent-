import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import agent
import config
import tools
from inventory import ValidationError, amount, csv_bytes, inr, load_table, quantity, scaled, validate_table
from stocklist import Stocklist

ROOT = Path(__file__).resolve().parents[1]


class InventoryTests(unittest.TestCase):
    def test_formats_are_exact(self):
        self.assertEqual(scaled('1,25,000.50', scale=100), 12500050)
        self.assertEqual(scaled('1,000.125'), 1000125)
        self.assertEqual(inr('123.99'), '₹123.99')
        self.assertEqual(quantity(125), '0.125')
        for value in ('bad', 'NaN', 'Infinity', '1,00', '1.0001', '-1', ''):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                scaled(value)

    def test_import_requires_columns_and_values(self):
        records, errors = validate_table(pd.DataFrame([{'Item Name': 'Widget', 'Current Stock': '0'}]))
        self.assertFalse(records)
        self.assertTrue(any('reorder_level' in e for e in errors))
        rows, errors = validate_table(load_table(ROOT/'inventory.xlsx'))
        self.assertFalse(errors)
        bad = dict(rows[0], current_stock='1,000', unit_price='1,250.50')
        records, errors = validate_table(pd.DataFrame([bad]))
        self.assertFalse(errors)
        self.assertEqual(records[0]['current_stock'], '1000')
        self.assertEqual(records[0]['unit_price'], '1250.50')
        for field in ('unit_price', 'current_stock', 'reorder_level'):
            _, errors = validate_table(pd.DataFrame([dict(bad, **{field: ''})]))
            self.assertTrue(errors)

    def test_duplicate_skus_and_mapping_are_rejected(self):
        rows, _ = validate_table(load_table(ROOT/'inventory.xlsx'))
        _, errors = validate_table(pd.DataFrame([rows[0], dict(rows[0], item_code=rows[0]['item_code'].lower())]))
        self.assertTrue(any('Duplicate SKU' in e for e in errors))
        df = pd.DataFrame([{'SKU': 'A', 'Item Code': 'B'}])
        _, errors = validate_table(df)
        self.assertTrue(any('Multiple columns' in e for e in errors))

    def test_csv_export_neutralizes_formulas(self):
        data = csv_bytes([{'name': '=HYPERLINK("bad")'}]).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", data)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'inventory.sqlite3'
        self.store = Stocklist(self.path)
        self.supplier = self.store.save_supplier('Supplier', 'orders@example.invalid', actor='Owner')
        self.raw = dict(item_code='SKU-ONE', item_name='Widget', unit='Pcs', unit_price='12.75', selling_price='18',
                        reorder_level='10', reorder_qty='20', barcode='12345')
        self.product = self.store.save_product(self.raw, opening='5', supplier_id=self.supplier, actor='Owner', token='product')

    def po(self, token='po', qty='20'):
        return self.store.create_po(self.supplier, [{'product_id':self.product,'qty':qty,'price':'12.75'}], actor='Owner', token=token)

    def approve(self, oid):
        self.store.approve_po(oid, actor='Owner', revision=self.store.order(oid)['revision'])

    def place(self, oid):
        self.approve(oid)
        self.store.place_manually(oid, 'Supplier phone confirmation 001', actor='Owner', revision=1)

    def test_stock_persists_and_cannot_go_negative(self):
        self.store.move_stock(self.product, 'sale', '2', 'Customer sale', actor='Shop', token='sale')
        self.assertEqual(Stocklist(self.path).products()[0]['stock'], 3000)
        with self.assertRaises(ValidationError):
            self.store.move_stock(self.product, 'damage', '4', 'Broken', actor='Shop', token='damage')
        self.assertEqual(len(self.store.movements()), 2)

    def test_idempotent_movements_and_conflicting_tokens(self):
        args = (self.product, 'receipt', '2.125', 'Delivery')
        first = self.store.move_stock(*args, actor='Shop', token='movement')
        self.assertEqual(first, self.store.move_stock(*args, actor='Shop', token='movement'))
        self.assertEqual(self.store.products()[0]['stock'], 7125)
        with self.assertRaises(ValidationError):
            self.store.move_stock(self.product, 'receipt', '3', 'Delivery', actor='Shop', token='movement')

    def test_counts_require_unchanged_balance_and_reason(self):
        self.store.move_stock(self.product, 'stock_count', '3', 'Physical count', actor='Shop', token='count', expected_stock=5000)
        self.assertEqual(self.store.products()[0]['stock'], 3000)
        with self.assertRaises(ValidationError):
            self.store.move_stock(self.product, 'stock_count', '5', 'Stale count', actor='Shop', token='count2', expected_stock=5000)
        with self.assertRaises(ValidationError):
            self.store.move_stock(self.product, 'receipt', '2', '', actor='Shop', token='missing')

    def test_append_only_ledger(self):
        with self.assertRaises(ValidationError), self.store.connect(True) as db:
            db.execute('DELETE FROM movements')
        with self.assertRaises(ValidationError), self.store.connect(True) as db:
            db.execute("UPDATE audit SET action='hidden'")

    def test_unit_and_stale_product_edits(self):
        with self.assertRaises(ValidationError):
            self.store.save_product(dict(self.raw, unit='Kg'), actor='Owner', token='unit', product_id=self.product, version=1)
        self.store.save_product(dict(self.raw, item_name='New name'), actor='Owner', token='edit', product_id=self.product, version=1)
        with self.assertRaises(ValidationError):
            self.store.save_product(self.raw, actor='Owner', token='stale', product_id=self.product, version=1)

    def test_same_supplier_name_different_email_remains_separate(self):
        sid = self.store.save_supplier('Supplier', 'other@example.invalid', actor='Owner')
        self.assertNotEqual(sid, self.supplier)
        self.assertEqual(len(self.store.suppliers()), 2)

    def test_import_atomicity_and_duplicate_protection(self):
        rows, _ = validate_table(load_table(ROOT/'inventory.xlsx'))
        self.store.import_products(rows, actor='Owner', token='sample')
        self.assertEqual(self.store.import_products(rows, actor='Owner', token='sample'), 8)
        before = len(self.store.products())
        new = dict(rows[0], item_code='NEW', barcode='')
        with self.assertRaises(ValidationError):
            self.store.import_products([new, rows[1]], actor='Owner', token='bad-import')
        self.assertEqual(len(self.store.products()), before)
        with self.assertRaises(ValidationError):
            self.store.import_products(rows, actor='Owner', token='different-import')

    def test_unique_orders_and_idempotent_creation(self):
        a = self.po()
        self.assertEqual(a, self.po())
        b = self.po('second')
        self.assertNotEqual(self.store.order(a)['number'], self.store.order(b)['number'])
        self.assertEqual(self.store.order(a)['total'], 25500)

    def test_reorder_rechecks_pending_orders_under_lock(self):
        self.assertEqual(len(self.store.recommendations()), 1)
        oid = self.store.create_po(self.supplier, [], actor='Owner', token='reorder', reorder=True)
        self.assertFalse(self.store.recommendations())
        with self.assertRaises(ValidationError):
            self.store.create_po(self.supplier, [], actor='Owner', token='stale-reorder', reorder=True)
        self.store.cancel_po(oid, 'No longer required', actor='Owner')
        self.assertEqual(len(self.store.recommendations()), 1)

    def test_partial_receipt_full_receipt_and_replay(self):
        oid = self.po(); self.place(oid)
        line = self.store.order(oid)['lines'][0]['id']
        self.assertEqual(self.store.products()[0]['incoming'], 20000)
        result = self.store.receive_po(oid, {line:'7'}, actor='Shop', token='receive1', reference='DN1')
        self.assertEqual(result, 'partial')
        self.assertEqual(self.store.products()[0]['stock'], 12000)
        self.assertEqual(self.store.products()[0]['incoming'], 13000)
        self.assertEqual(self.store.receive_po(oid, {line:'7'}, actor='Shop', token='receive1', reference='DN1'), 'partial')
        with self.assertRaises(ValidationError):
            self.store.receive_po(oid, {line:'14'}, actor='Shop', token='too-many', reference='DN2')
        self.store.receive_po(oid, {line:'13'}, actor='Shop', token='receive2', reference='DN2')
        self.assertEqual(self.store.order(oid)['state'], 'received')
        self.assertEqual(self.store.products()[0]['stock'], 25000)
        self.assertEqual(self.store.products()[0]['incoming'], 0)

    def test_receipt_before_placing_or_wrong_line_rejected(self):
        oid = self.po()
        line = self.store.order(oid)['lines'][0]['id']
        with self.assertRaises(ValidationError):
            self.store.receive_po(oid, {line:'1'}, actor='Shop', token='early', reference='DN')
        self.place(oid)
        with self.assertRaises(ValidationError):
            self.store.receive_po(oid, {99999:'1'}, actor='Shop', token='foreign', reference='DN')

    def test_cancellation_keeps_received_stock(self):
        oid = self.po(); self.place(oid)
        line = self.store.order(oid)['lines'][0]['id']
        self.store.receive_po(oid, {line:'2'}, actor='Shop', token='r1', reference='DN')
        self.store.cancel_po(oid, 'Supplier cancelled remainder', actor='Owner')
        self.assertEqual(self.store.products()[0]['stock'], 7000)
        self.assertEqual(self.store.products()[0]['incoming'], 0)

    def test_preview_does_not_consume_approval_or_send(self):
        oid = self.po()
        sender = unittest.mock.Mock()
        self.store.send_po(oid, actor='Owner', dry_run=True, sender=sender)
        self.assertEqual(self.store.order(oid)['state'], 'draft')
        self.approve(oid)
        self.store.send_po(oid, actor='Owner', dry_run=True, sender=sender)
        self.assertEqual(self.store.order(oid)['state'], 'approved')
        sender.assert_not_called()

    def test_send_requires_exact_approval_and_blocks_repeat(self):
        oid = self.po()
        sender = unittest.mock.Mock(return_value={'status':'ok','mode':'live'})
        with self.assertRaises(ValidationError):
            self.store.send_po(oid, actor='Owner', dry_run=False, sender=sender)
        self.approve(oid)
        approved = self.store.order(oid)
        self.store.send_po(oid, actor='Owner', dry_run=False, sender=sender)
        sender.assert_called_once_with(approved['supplier_email'], approved['subject'], approved['body'], dry_run=False)
        with self.assertRaises(ValidationError):
            Stocklist(self.path).send_po(oid, actor='Owner', dry_run=False, sender=sender)
        self.assertEqual(sender.call_count, 1)

    def test_body_tampering_and_revisions_invalidate_approval(self):
        oid = self.po(); self.approve(oid)
        with self.store.connect(True) as db:
            db.execute("UPDATE purchase_orders SET body='tampered' WHERE id=?", (oid,))
        with self.assertRaises(ValidationError):
            self.store.send_po(oid, actor='Owner', dry_run=False, sender=unittest.mock.Mock())
        self.store.revise_po(oid, [{'product_id':self.product,'qty':'3','price':'1.25'}], 'New price', actor='Owner', revision=1)
        order = self.store.order(oid)
        self.assertEqual((order['state'], order['revision'], order['total']), ('draft', 2, 375))
        self.assertEqual(order['approval_hash'], '')
        self.approve(oid)
        self.assertIn('₹3.75', self.store.order(oid)['body'])

    def test_unknown_delivery_cannot_retry_without_reconciliation(self):
        oid = self.po(); self.approve(oid)
        sender = unittest.mock.Mock(side_effect=TimeoutError('No delivery acknowledgement'))
        self.store.send_po(oid, actor='Owner', dry_run=False, sender=sender)
        self.assertEqual(self.store.order(oid)['state'], 'delivery_unknown')
        with self.assertRaises(ValidationError):
            self.store.send_po(oid, actor='Owner', dry_run=False, sender=sender)
        self.store.reconcile_delivery(oid, False, 'Supplier and mailbox checked', actor='Owner')
        self.assertEqual(self.store.order(oid)['state'], 'approved')

    def test_known_failure_allows_retry(self):
        oid = self.po(); self.approve(oid)
        self.store.send_po(oid, actor='Owner', dry_run=False,
                           sender=lambda *a,**kw:{'status':'error','delivery':'not_sent','message':'Missing credentials'})
        self.assertEqual(self.store.order(oid)['state'], 'approved')

    def test_concurrent_sales_cannot_oversell(self):
        def sell(n):
            try:
                self.store.move_stock(self.product, 'sale', '4', 'Sale', actor='Shop', token=f'sale{n}')
                return True
            except ValidationError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(sell, [1, 2]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.products()[0]['stock'], 1000)

    def test_backup_restore_round_trip(self):
        backup = Path(self.temp.name)/'backup.sqlite3'
        backup.write_bytes(self.store.backup())
        self.store.move_stock(self.product, 'sale', '1', 'Sale', actor='Shop', token='afterbackup')
        agent.restore_backup(backup, self.path)
        restored = Stocklist(self.path)
        self.assertEqual(restored.products()[0]['stock'], 5000)
        self.assertEqual(restored.health()['integrity'], 'ok')
        self.assertEqual(len(list(Path(self.temp.name).glob('*.before-restore-*.sqlite3'))), 1)


class TransportTests(unittest.TestCase):
    def test_no_retry_after_ambiguous_smtp_failure(self):
        with patch.object(config,'GMAIL_USER','sender@example.invalid'), patch.object(config,'GMAIL_APP_PASSWORD','fake'), patch.object(tools.smtplib,'SMTP_SSL') as smtp:
            smtp.return_value.__enter__.return_value.send_message.side_effect = TimeoutError('acknowledgement lost')
            result = json.loads(tools.send_email('orders@example.invalid', 'PO 1', 'Approved body', dry_run=False))
            self.assertEqual(result['delivery'], 'unknown')
            self.assertEqual(smtp.call_count, 1)

    def test_live_flag_does_not_modify_global_config(self):
        with patch.object(config, 'DRY_RUN', True), patch.object(agent, 'run_agent') as run:
            agent.main(['--no-dry-run'])
            self.assertFalse(run.call_args.kwargs['dry_run'])
            self.assertTrue(config.DRY_RUN)

    def test_invalid_recipient_blocked_before_transport(self):
        with patch.object(tools.smtplib, 'SMTP_SSL') as smtp:
            result = json.loads(tools.send_email('bad\r\nBcc: x@y.com', 'PO', 'body', dry_run=False))
            self.assertEqual(result['delivery'], 'not_sent')
            smtp.assert_not_called()


if __name__ == '__main__':
    unittest.main()
