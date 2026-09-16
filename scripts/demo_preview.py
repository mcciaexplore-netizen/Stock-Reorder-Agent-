"""Start a separate sample business, or resume one without resetting its data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, help='Existing demo-access.json to resume')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    if args.resume:
        access_path = args.resume.resolve()
        manifest = json.loads(access_path.read_text(encoding='utf-8'))
        database = Path(manifest['database']).resolve()
    else:
        folder = Path(tempfile.mkdtemp(prefix='stocklist-business-demo-'))
        database, access_path = folder / 'demo.sqlite3', folder / 'demo-access.json'
    os.environ.update(DATABASE_PATH=str(database), STOCKLIST_DEMO_ACCESS=str(access_path),
                      GMAIL_USER='', GMAIL_APP_PASSWORD='', DRY_RUN='true')

    from demo_access import demo_profiles, write_demo_access
    from demo_data import seed_sample_data
    from demo_operations import seed_operations_demo
    from offline import entry_sheet
    from stocklist import Stocklist
    if args.resume:
        profiles = demo_profiles(database, access_path)
        owner = next((p for p in profiles if p['role'] == 'owner'), None)
        if owner is None:
            parser.error('This file does not enable owner access to its original demo database.')
    else:
        owner = dict(username='demo', password=secrets.token_urlsafe(24))
    store = Stocklist(database)
    if args.resume:
        store.login(owner['username'], owner['password'])
    else:
        store.bootstrap(owner['username'], 'Demo owner', owner['password'])
    seed_sample_data(store)
    seed_operations_demo(store)
    if not args.resume:
        write_demo_access(store, access_path, owner['username'], owner['password'])
    (database.parent / 'offline.html').write_bytes(entry_sheet(
        store.products(), store.locations(), store.settings()['workspace_id'], store.batches()))
    store.logout()
    print('Demo access file: ' + str(access_path), flush=True)
    print('Use the Owner, Warehouse, Accountant or Read-only demo button to sign in.', flush=True)
    print('Resume this sample business with: python scripts/demo_preview.py --resume "' + str(access_path) + '"', flush=True)
    os.chdir(ROOT)
    from streamlit.web import cli
    sys.argv = ['streamlit', 'run', str(ROOT / 'streamlit_app.py'), '--server.port', str(args.port),
                '--server.address', '127.0.0.1', '--server.headless', 'true']
    cli.main()


if __name__ == '__main__':
    main()
