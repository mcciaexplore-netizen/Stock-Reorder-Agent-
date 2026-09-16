"""Opt-in demo shortcuts, bound to one database; all logins use normal authentication."""
import json
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3

from inventory import ValidationError

PROFILES = {
    'owner': ('Owner demo', 'Explore every feature and manage the sample business.'),
    'warehouse': ('Warehouse demo', 'Receive stock, transfer items and record operations.'),
    'accountant': ('Accountant demo', 'Review bills, sales invoices, payments and reports.'),
    'viewer': ('Read-only demo', 'Browse the sample business without changing records.'),
}


def demo_profiles(database_path, access_path):
    """Fail closed for missing, malformed, stale or cross-database demo access files."""
    if not access_path:
        return []
    try:
        path = Path(database_path).resolve()
        manifest = json.loads(Path(access_path).read_text(encoding='utf-8'))
        if manifest['version'] != 1 or Path(manifest['database']).resolve() != path:
            return []
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            workspace = db.execute("SELECT value FROM settings WHERE key='workspace_id'").fetchone()
            if not workspace or workspace[0] != manifest['workspace_id']:
                return []
            result = []
            for account in manifest['accounts']:
                username, password, role = account['username'], account['password'], account['role']
                if role not in PROFILES or not isinstance(password, str) or not 12 <= len(password) <= 256:
                    return []
                active = db.execute('SELECT role FROM users WHERE username=? AND active=1', (username,)).fetchone()
                if active and active[0] == role:
                    label, description = PROFILES[role]
                    result.append(dict(username=username, password=password, role=role,
                                       label=label, description=description))
            return result
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return []


def write_demo_access(store, access_path, owner_username, owner_password):
    """Provision demo staff without changing existing accounts or their passwords."""
    store.login(owner_username, owner_password)
    if store.identity()['role'] != 'owner':
        raise ValidationError('An owner must prepare demo access.')
    path = Path(access_path)
    existing = {p['role']: p for p in demo_profiles(store.path, path)}
    accounts = [dict(username=owner_username, password=owner_password, role='owner')]
    usernames = {u['username'] for u in store.users()}
    for role in PROFILES:
        if role == 'owner':
            continue
        if role in existing:
            account = existing[role]
        else:
            username = 'demo-' + role
            if username in usernames:
                username += '-' + secrets.token_hex(3)
            account = dict(username=username, password=secrets.token_urlsafe(24), role=role)
            store.save_user(username, 'Demo ' + role, role, account['password'], actor='Demo setup')
            usernames.add(username)
        accounts.append({k: account[k] for k in ('username', 'password', 'role')})
    manifest = dict(version=1, database=str(Path(store.path).resolve()),
                    workspace_id=store.settings()['workspace_id'], accounts=accounts)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(path)
    return path
