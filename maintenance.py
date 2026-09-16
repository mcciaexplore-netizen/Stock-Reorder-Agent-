"""Local scheduled checks. Run as a separate process using a dedicated owner account."""
import argparse
import getpass
import os
import time

import config
from stocklist import Stocklist


def main():
    parser=argparse.ArgumentParser(description='Run Stocklist backup and exception checks')
    parser.add_argument('--database',default=str(config.DATABASE_PATH))
    parser.add_argument('--interval',type=int,default=0,help='Seconds between checks; 0 runs once, minimum recurring interval is 60.')
    args=parser.parse_args()
    if args.interval and args.interval<60:parser.error('Use an interval of at least 60 seconds.')
    store=Stocklist(args.database)
    if store.needs_setup():parser.error('Create an owner in the app before scheduling maintenance.')
    username=os.getenv('STOCKLIST_USERNAME') or input('Owner username: ')
    password=os.getenv('STOCKLIST_PASSWORD') or getpass.getpass('Password: ')
    while True:
        store.login(username,password)
        try:
            print(store.run_maintenance(actor='Maintenance'),flush=True)
        finally:
            store.logout()
        if not args.interval:break
        time.sleep(args.interval)


if __name__=='__main__':
    main()
