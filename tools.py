"""Validated JSON adapters and email transport. Business state lives in stocklist.py."""
from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage

import config
from inventory import (ValidationError, amount, email, inr, line_value, load_table,
                       quantity, scaled, validate_product, validate_table)


def _ok(payload):
    return json.dumps({'status': 'ok', **payload})


def _err(message, **extra):
    return json.dumps({'status': 'error', 'message': str(message), **extra})


def _inr(value):
    return inr(value)


def read_inventory(xlsx_path):
    try:
        records, errors = validate_table(load_table(xlsx_path))
        if errors:
            return _err('\n'.join(errors))
        return _ok({'count': len(records), 'items': records})
    except Exception as exc:
        return _err(exc)


def find_low_stock(inventory_json):
    try:
        data = json.loads(inventory_json)
        if isinstance(data, dict) and data.get('status') == 'error':
            raise ValidationError(data.get('message', 'Invalid inventory.'))
        items = data.get('items', []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValidationError('Inventory items must be a list.')
        low = []
        for raw in items:
            if 'reorder_level' not in raw or 'current_stock' not in raw:
                raise ValidationError('Current stock and reorder level are required.')
            row = validate_product(raw)
            current = scaled(raw['current_stock'], 'Current stock')
            level = scaled(row['reorder_level'])
            if current < level:
                qty = scaled(row['reorder_qty']) or (level * 3 + 1) // 2 - current
                row.update(current_stock=quantity(current), shortage=quantity(level-current),
                           reorder_qty=quantity(qty), line_total=amount(line_value(qty, scaled(row['unit_price'], 'Price', 100))))
                low.append(row)
        from po_utils import group_low_stock_items
        groups = group_low_stock_items(low)
        return _ok({'low_stock_count': len(low), 'low_stock_items': low,
                    'supplier_count': len(groups), 'supplier_summary': [
                        {k: v for k, v in g.items() if k != 'items'} for g in groups]})
    except Exception as exc:
        return _err(exc)


def send_email(to_email, subject, body, *, dry_run=None):
    """Transport only. Never automatically retry after an uncertain SMTP result."""
    dry_run = config.DRY_RUN if dry_run is None else dry_run
    try:
        recipient = email(to_email, required=True)
        if not subject.strip() or '\r' in subject or '\n' in subject:
            raise ValidationError('Email subject must be one non-empty line.')
        if not body.strip():
            raise ValidationError('Email body cannot be empty.')
        if dry_run:
            return _ok({'mode': 'dry_run', 'to': recipient})
        sender = email(config.GMAIL_USER, required=True)
        if not config.GMAIL_APP_PASSWORD:
            raise ValidationError('Set GMAIL_USER and GMAIL_APP_PASSWORD before sending email.')
        message = EmailMessage()
        message['From'] = sender
        message['To'] = recipient
        message['Subject'] = subject
        message.set_content(body)
    except (ValidationError, ValueError) as exc:
        return _err(exc, delivery='not_sent')
    attempted = False
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=15, context=ssl.create_default_context()) as smtp:
            smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            attempted = True
            refused = smtp.send_message(message)
            if refused:
                return _err('The recipient was rejected by the mail server.', delivery='not_sent')
        return _ok({'mode': 'live', 'sent_to': recipient, 'subject': subject})
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        return _err(exc, delivery='not_sent')
    except Exception as exc:
        return _err(exc, delivery='unknown' if attempted else 'not_sent')


def log_po_sent(po_number, supplier_name='', supplier_email='', items_count=0, total_value='0'):
    """Compatibility adapter: successful sends are already recorded transactionally."""
    from stocklist import Stocklist
    store = Stocklist(config.DATABASE_PATH)
    matching = [o for o in store.orders() if o['number'] == po_number and o['state'] in ('sent', 'partial', 'received')]
    return _ok({'logged': po_number, 'storage': 'database'}) if matching else _err('No placed order exists with that number.')
