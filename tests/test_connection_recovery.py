import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest
import config
import cloud_database
from deployment_errors import handle_script_error
from stocklist import Stocklist

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'test.sqlite3'
        settings = patch.object(config, 'DATABASE_PATH', self.path)
        settings.start()
        self.addCleanup(settings.stop)
        self.store = Stocklist(self.path)
        self.token = self.store.bootstrap('owner', 'Owner', 'correct horse battery staple')

    def app(self, authenticated=False):
        app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=60)
        if authenticated:
            app.session_state['auth_token'] = self.token
        return app.run()

    def test_identity_outage_shows_retry(self):
        with patch.object(Stocklist, 'identity', side_effect=sqlite3.OperationalError('connection failed')):
            app = self.app()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertTrue(any(b.label == 'Try again' for b in app.button))

    def test_login_outage_keeps_login_form(self):
        app = self.app()
        next(t for t in app.text_input if t.label == 'Username').input('owner')
        next(t for t in app.text_input if t.label == 'Password').input('correct horse battery staple')
        with patch.object(Stocklist, 'login', side_effect=sqlite3.OperationalError('connection failed')):
            next(b for b in app.button if b.label == 'Sign in').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Could not reach' in e.value for e in app.error))
        self.assertNotIn('auth_token', app.session_state)

    def test_logout_outage_still_clears_local_authentication(self):
        app = self.app(authenticated=True)
        with patch.object(Stocklist, 'logout', side_effect=sqlite3.OperationalError('connection failed')):
            next(b for b in app.button if b.label == 'Sign out').click().run()
        self.assertFalse(app.exception)
        self.assertNotIn('auth_token', app.session_state)
        self.assertTrue(any('server session could not be revoked' in w.value for w in app.warning))
        self.assertEqual(app.title[0].value, 'Sign in to Stocklist')

    def test_connection_is_closed_when_configuration_fails(self):
        raw = Mock()
        raw.execute.side_effect = sqlite3.OperationalError('configuration failed')
        self.store._initializing = True
        with patch.object(cloud_database, 'connect', return_value=raw):
            with self.assertRaises(sqlite3.OperationalError):
                with self.store.connect():
                    self.fail('Should not yield a failed connection')
        raw.close.assert_called_once()

    def test_network_errors_are_sanitized(self):
        driver = Mock(Error=sqlite3.Error, IntegrityError=sqlite3.IntegrityError)
        connection = cloud_database.Connection(Mock(), driver)
        with self.assertRaises(sqlite3.OperationalError) as raised:
            connection.call(Mock(side_effect=TimeoutError('private connection string')))
        self.assertNotIn('private', str(raised.exception))

    def test_deployment_error_handler_preserves_programming_errors(self):
        with patch('deployment_errors.st.error') as message:
            self.assertTrue(handle_script_error(sqlite3.OperationalError('private details')))
            self.assertNotIn('private', message.call_args.args[0])
            self.assertFalse(handle_script_error(TypeError('programming error')))


if __name__ == '__main__':
    unittest.main()
