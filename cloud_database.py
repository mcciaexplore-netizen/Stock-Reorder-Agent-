"""SQLite Cloud transport; local installations continue to use sqlite3.

Connections are never cached or shared between threads. Business transactions
remain on one remote connection, including BEGIN IMMEDIATE and rollback.
"""
from contextlib import closing
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def is_cloud(path):
    return str(path).startswith('sqlitecloud://')


class Row(tuple):
    def __new__(cls, values, names):
        row = super().__new__(cls, values)
        row.names = names
        return row

    def keys(self):
        return self.names

    def __getitem__(self, key):
        if isinstance(key, str):
            key = [name.casefold() for name in self.names].index(key.casefold())
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor, connection):
        self.raw = cursor
        self.connection = connection

    def _row(self, value):
        if value is None or self.connection.row_factory is None:
            return value
        return Row(value, [column[0] for column in self.raw.description])

    def fetchone(self):
        return self._row(self.connection.call(self.raw.fetchone))

    def fetchall(self):
        return [self._row(row) for row in self.connection.call(self.raw.fetchall)]

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

    @property
    def lastrowid(self):
        return self.raw.lastrowid

    @property
    def rowcount(self):
        return self.raw.rowcount


class Connection:
    def __init__(self, raw, driver):
        self.raw = raw
        self.driver = driver
        self.row_factory = None
        self.in_transaction = False

    def call(self, fn, *args):
        try:
            return fn(*args)
        except self.driver.IntegrityError:
            raise sqlite3.IntegrityError('A database constraint rejected this change.') from None
        except (self.driver.Error, OSError):
            # Connection strings contain API keys. Never forward SDK messages.
            raise sqlite3.OperationalError('Cloud database request failed. Check database availability and credentials.') from None

    def execute(self, sql, parameters=()):
        cursor = Cursor(self.call(self.raw.execute, sql, parameters), self)
        command = sql.strip().split()[0].rstrip(';').upper()
        if command == 'BEGIN':
            self.in_transaction = True
        elif command in ('COMMIT', 'ROLLBACK'):
            self.in_transaction = False
        return cursor

    def executemany(self, sql, parameters):
        cursor = None
        for row in parameters:
            cursor = self.execute(sql, row)
        return cursor

    def commit(self):
        if self.in_transaction:
            self.execute('COMMIT')

    def rollback(self):
        if self.in_transaction:
            self.execute('ROLLBACK')

    def close(self):
        self.call(self.raw.close)

    def backup(self, destination):
        """Export a consistent read snapshot into a local SQLite backup."""
        self.execute('BEGIN')
        try:
            schema = self.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type='table' DESC,name").fetchall()
            tables = [row for row in schema if row[0] == 'table']
            destination.execute('PRAGMA foreign_keys=OFF')
            for _, _, sql in tables:
                destination.execute(sql)
            for _, name, _ in tables:
                quoted = '"' + name.replace('"', '""') + '"'
                rows = self.execute('SELECT * FROM ' + quoted).fetchall()
                if rows:
                    marks = ','.join('?' for _ in rows[0])
                    destination.executemany(f'INSERT INTO {quoted} VALUES({marks})', rows)
            if self.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                destination.execute('DELETE FROM sqlite_sequence')
                destination.executemany('INSERT INTO sqlite_sequence VALUES(?,?)', self.execute('SELECT * FROM sqlite_sequence').fetchall())
            for kind, _, sql in schema:
                if kind != 'table':
                    destination.execute(sql)
            version = int(self.execute('PRAGMA user_version').fetchone()[0])
            destination.execute(f'PRAGMA user_version={version}')
            destination.commit()
        except Exception:
            destination.rollback()
            raise
        finally:
            self.rollback()


def connect(path, timeout=15):
    if not is_cloud(path):
        return sqlite3.connect(path, timeout=timeout)
    import sqlitecloud
    try:
        parts = urlsplit(str(path))
        query = dict(parse_qsl(parts.query))
        query['timeout'] = str(timeout)
        query['connect_timeout'] = str(timeout)
        raw = sqlitecloud.connect(urlunsplit(parts._replace(query=urlencode(query))))
    except (sqlitecloud.Error, ValueError, OSError):
        raise sqlite3.OperationalError('Cannot connect to the cloud database. Check SQLITE_CLOUD_URL in deployment settings.') from None
    connection = Connection(raw, sqlitecloud)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
    except Exception:
        connection.close()
        raise
    return connection


def initialize(path, template_factory, version):
    """Initialize an empty remote database using the locally migrated schema.

    Existing cloud schemas must match this app; never auto-upgrade a remote
    business database without a provider backup and a separate migration.
    """
    with closing(connect(path)) as db:
        current = db.execute('PRAGMA user_version').fetchone()[0]
        if current == version:
            return
        if current != 0:
            raise sqlite3.OperationalError('Cloud database needs a backed-up schema migration before deploying this app version.')
        script = template_factory()
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        try:
            current = db.execute('PRAGMA user_version').fetchone()[0]
            if current == version:
                db.commit()
                return
            # SQLite Cloud pre-creates this vector-extension catalogue even in
            # a new database. Preserve it; do not mistake it for business data.
            # Keep the allowlist exact so other existing tables still block setup.
            if current != 0 or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*' AND name <> ?",
                                          ('_sqliteai_vector',)).fetchone():
                raise sqlite3.OperationalError('Choose an empty dedicated database or import a current Stocklist backup.')
            statement = ''
            for line in script.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    if statement.strip() not in ('BEGIN TRANSACTION;', 'COMMIT;'):
                        db.execute(statement)
                    statement = ''
            db.execute(f'PRAGMA user_version={int(version)}')
            db.commit()
        except Exception:
            db.rollback()
            raise
