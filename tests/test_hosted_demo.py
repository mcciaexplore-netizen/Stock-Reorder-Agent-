import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from streamlit.testing.v1 import AppTest
import config
from hosted_demo import DemoWorkspace
from inventory import ValidationError

ROOT = Path(__file__).resolve().parents[1]

class HostedDemoTests(unittest.TestCase):
    def test_isolation_permissions_and_email(self):
        with patch.dict('os.environ', {'SQLITE_CLOUD_URL': 'sqlitecloud://must-not-connect'}):
            first = DemoWorkspace('owner')
            second = DemoWorkspace('viewer')
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        owner = first.open(first.token)
        viewer = second.open(second.token)
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(owner.products())
        self.assertNotEqual(owner.settings()['workspace_id'], viewer.settings()['workspace_id'])
        owner.save_settings({'business_name': 'Changed demo'}, actor='Demo owner')
        self.assertNotEqual(viewer.settings()['business_name'], 'Changed demo')
        self.assertEqual(viewer.identity()['role'], 'viewer')
        with self.assertRaises(ValidationError):
            viewer.save_settings({'business_name': 'Forbidden'}, actor='Demo viewer')
        sender = Mock()
        with self.assertRaisesRegex(ValidationError, 'Email sending is disabled'):
            owner.send_po(1, actor='Demo owner', dry_run=False, sender=sender)
        sender.assert_not_called()

    def test_demo_works_without_live_database_and_exits(self):
        with patch.dict('os.environ', {'VERCEL': '1'}), patch.object(config, 'SQLITE_CLOUD_URL', ''):
            app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=120).run()
            self.assertFalse(app.exception)
            self.assertEqual(len([b for b in app.button if b.key.startswith('hosted_demo_')]), 4)
            app.button(key='hosted_demo_warehouse').click().run()
            self.assertFalse(app.exception)
            workspace = app.session_state['demo_workspace']
            self.assertEqual(workspace.open(app.session_state['auth_token']).identity()['role'], 'warehouse')
            path = workspace.path
            app.button(key='leave_demo').click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('auth_token', app.session_state)
            self.assertNotIn('demo_workspace', app.session_state)
            self.assertFalse(path.exists())

if __name__ == '__main__':
    unittest.main()
