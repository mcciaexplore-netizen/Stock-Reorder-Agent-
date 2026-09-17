"""Disposable, session-owned demo databases. Never uses the live connection URL."""
from pathlib import Path
import secrets
import tempfile

from demo_access import PROFILES
from demo_data import seed_sample_data
from demo_operations import seed_operations_demo
from stocklist import Stocklist


class DemoWorkspace:
    def __init__(self, role):
        if role not in PROFILES:
            raise ValueError('Unknown demo role')
        self.folder = tempfile.TemporaryDirectory(prefix='stocklist-session-demo-')
        self.path = Path(self.folder.name) / 'demo.sqlite3'
        try:
            store = Stocklist(self.path)
            password = secrets.token_urlsafe(24)
            store.bootstrap('demo', 'Demo owner', password)
            seed_sample_data(store)
            seed_operations_demo(store)
            if role != 'owner':
                store.save_user('demo-' + role, 'Demo ' + role, role, password, actor='Demo setup')
            store.logout()
            self.token = store.login('demo' if role == 'owner' else 'demo-' + role, password)
        except Exception:
            self.close()
            raise

    def open(self, token):
        store = Stocklist(self.path, session_token=token)
        store.demo = True
        return store

    def close(self):
        self.folder.cleanup()
