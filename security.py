"""Local accounts, revocable sessions and service-level role checks."""
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import inspect
import secrets
import sqlite3
import time

from inventory import ValidationError, text

ROLES = {
    'owner': {'read', 'catalogue', 'inventory', 'purchase', 'approve', 'accounts', 'admin', 'backup', 'documents'},
    'manager': {'read', 'catalogue', 'inventory', 'purchase', 'approve', 'accounts', 'documents'},
    'purchaser': {'read', 'purchase', 'documents'},
    'warehouse': {'read', 'inventory', 'documents'},
    'accountant': {'read', 'accounts', 'documents'},
    'viewer': {'read'},
}
PERMISSIONS = {
    'save_supplier':'catalogue', 'save_product':'catalogue', 'import_products':'catalogue',
    'move_stock':'inventory', 'create_po':'purchase', 'revise_po':'purchase', 'approve_po':'approve',
    'place_manually':'approve', 'send_po':'approve', 'reconcile_delivery':'approve', 'cancel_po':'approve',
    'receive_po':'inventory', 'backup':'backup', 'save_user':'admin', 'users':'admin', 'save_settings':'admin',
    'save_location':'catalogue', 'transfer':'inventory', 'reserve':'inventory', 'release_reservation':'inventory',
    'save_product_options':'catalogue', 'save_conversion':'catalogue', 'save_batch':'inventory',
    'save_quote':'purchase', 'order_quote':'purchase', 'save_bill':'accounts', 'accept_bill':'accounts',
    'add_attachment':'documents', 'scan_attachment':'documents', 'save_job':'catalogue', 'consume_job':'inventory',
    'lend':'inventory', 'return_loan':'inventory', 'save_recipe':'catalogue', 'assemble':'inventory',
    'save_customer':'accounts', 'issue_invoice':'accounts', 'credit_invoice':'accounts', 'record_payment':'accounts',
    'save_repair':'inventory', 'close_repair':'inventory', 'set_order_due':'purchase',
    'run_maintenance':'backup', 'refresh_alerts':'read', 'acknowledge_alert':'documents', 'sync_movements':'inventory',
    'record_import_issue':'catalogue',
    'create_customer_quote':'accounts', 'confirm_customer_quote':'accounts', 'cancel_customer_quote':'accounts',
    'set_sales_commitment':'accounts', 'cancel_sales_order':'accounts', 'dispatch_sales_order':'inventory', 'invoice_sales_dispatch':'accounts',
    'create_work_order':'inventory', 'advance_work_order':'inventory', 'issue_work_materials':'inventory',
    'record_work_cost':'inventory', 'record_work_scrap':'inventory', 'complete_work_output':'inventory', 'cancel_work_order':'inventory',
    'open_quality_inspection':'inventory', 'record_quality_result':'inventory', 'route_quality_rework':'inventory', 'dispose_quality_stock':'inventory',
    'create_jobwork':'inventory', 'receive_jobwork_material':'inventory', 'reconcile_jobwork':'inventory', 'close_jobwork':'inventory',
}


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValidationError('Use a password of 12 to 256 characters.')
    salt = salt or secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256*1024*1024)
    return salt.hex() + ':' + hashed.hex()


def matches(password, stored):
    try:
        salt, _ = stored.split(':')
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


class Security:
    @contextmanager
    def _auth_db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def needs_setup(self):
        with self._auth_db() as db:
            return not db.execute('SELECT 1 FROM users LIMIT 1').fetchone()

    def bootstrap(self, username, name, password):
        username = text(username, 'Username', required=True, limit=80).casefold()
        name = text(name, 'Name', required=True, limit=100)
        hashed = password_hash(password)
        token = secrets.token_urlsafe(32)
        with self._auth_db() as db:
            if db.execute('SELECT 1 FROM users').fetchone():
                raise ValidationError('An owner account already exists. Sign in.')
            uid = db.execute("INSERT INTO users(username,name,password,role,created_at) VALUES(?,?,?,'owner',datetime('now'))", (username,name,hashed)).lastrowid
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,int(time.time())+8*3600))
            self._audit(db, name, 'owner_created', username, {})
        self.session_token=token
        return token

    def login(self, username, password):
        username = text(username, 'Username', required=True, limit=80).casefold()
        epoch = int(time.time())
        token = None
        with self._auth_db() as db:
            attempt = db.execute('SELECT * FROM login_attempts WHERE username=?', (username,)).fetchone()
            if attempt and attempt['locked_until'] > epoch:
                raise ValidationError('Too many attempts. Try again in 15 minutes.')
            user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            dummy = '00'*16 + ':' + '00'*64
            valid = matches(password, user['password'] if user else dummy)
            if not user or not user['active'] or not valid:
                failures = (attempt['failures'] if attempt and attempt['locked_until'] == 0 else 0) + 1
                db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (username, failures, epoch+900 if failures>=5 else 0))
            else:
                db.execute('DELETE FROM login_attempts WHERE username=?', (username,))
                db.execute('DELETE FROM sessions WHERE expires<=?', (epoch,))
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], epoch+8*3600))
        if token is None:
            raise ValidationError('Incorrect username or password.')
        self.session_token = token
        return token

    def identity(self):
        with self._auth_db() as db:
            if not db.execute('SELECT 1 FROM users').fetchone():
                return None  # Local maintenance API before account setup; UI never exposes data in this state.
            token_hash = hashlib.sha256((self.session_token or '').encode()).hexdigest()
            user = db.execute('SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1', (token_hash,int(time.time()))).fetchone()
            if not user:
                raise ValidationError('Sign in to continue. Your session may have expired.')
            return dict(user)

    def logout(self):
        with self._auth_db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256((self.session_token or '').encode()).hexdigest(),))
        self.session_token = None

    def allowed(self, permission):
        identity = self.identity()
        return identity is None or permission in ROLES.get(identity['role'], set())

    def users(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,username,name,role,active FROM users ORDER BY username')]

    def save_user(self, username, name, role, password='', active=True, *, actor, user_id=None):
        username = text(username,'Username',required=True,limit=80).casefold()
        name = text(name,'Name',required=True,limit=100)
        if role not in ROLES:
            raise ValidationError('Choose a supported role.')
        hashed = password_hash(password) if password else None
        with self.connect(True) as db:
            if user_id:
                old = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                if not old:
                    raise ValidationError('User no longer exists.')
                if old['role']=='owner' and old['active'] and (role!='owner' or not active):
                    if db.execute("SELECT COUNT(*) FROM users WHERE role='owner' AND active=1").fetchone()[0]<=1:
                        raise ValidationError('Keep at least one active owner.')
                db.execute('UPDATE users SET username=?,name=?,role=?,password=?,active=? WHERE id=?', (username,name,role,hashed or old['password'],int(active),user_id))
                db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            else:
                if not hashed:
                    raise ValidationError('A password is required for a new user.')
                user_id = db.execute("INSERT INTO users(username,name,password,role,active,created_at) VALUES(?,?,?,?,?,datetime('now'))", (username,name,hashed,role,int(active))).lastrowid
            self._audit(db,actor,'user_saved',user_id,{'role':role,'active':active})
        return user_id


def protect(cls):
    """Guard every business method, including newly added ones (read-only by default)."""
    excluded = {'connect','needs_setup','bootstrap','login','logout','identity','allowed','draft_email'}
    for name in dir(cls):
        method = getattr(cls,name)
        if name.startswith('_') or name in excluded or not callable(method):
            continue
        permission = PERMISSIONS.get(name,'read')
        takes_actor = 'actor' in inspect.signature(method).parameters
        def guarded(fn, permission, takes_actor):
            @wraps(fn)
            def call(self,*args,**kwargs):
                who = self.identity()
                if who:
                    if permission not in ROLES.get(who['role'],set()):
                        raise ValidationError(f'Your role does not allow this action ({permission}).')
                    if takes_actor:
                        kwargs['actor'] = who['name']
                return fn(self,*args,**kwargs)
            return call
        setattr(cls,name,guarded(method,permission,takes_actor))
    return cls
