"""Compatibility helpers for validated spreadsheet previews."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

from inventory import inr


def po_number(index, today=None):
    """Preview identifier only; permanent orders use the database sequence."""
    return f'PREVIEW-{(today or date.today()):%Y%m%d}-{index:03d}-{uuid4().hex[:12]}'


def group_low_stock_items(items):
    groups = {}
    for item in items:
        name = str(item.get('supplier_name') or 'Unassigned supplier').strip()
        address = str(item.get('supplier_email') or '').strip().lower()
        key = (name.casefold(), address)
        group = groups.setdefault(key, {'supplier_name': name, 'supplier_email': address, 'items': []})
        group['items'].append(item)
    result = []
    for key in sorted(groups):
        group = groups[key]
        group['items_count'] = len(group['items'])
        group['total_value'] = str(sum((Decimal(str(i.get('line_total', 0))) for i in group['items']), Decimal(0)))
        result.append(group)
    return result


def build_po_email(supplier, number, today=None):
    import config
    subject = f'Purchase Order {number} - {supplier["supplier_name"]}'
    rows = [f'{i["item_name"]} [{i["item_code"]}]\n  {i["reorder_qty"]} {i["unit"]} at {inr(i["unit_price"])} = {inr(i["line_total"])}'
            for i in supplier['items']]
    total = sum((Decimal(str(i['line_total'])) for i in supplier['items']), Decimal(0))
    body = f'Dear {supplier["supplier_name"]},\n\nPurchase Order {number}\nDate: {today or date.today()}\nFrom: {config.BUSINESS_NAME}\n\n'
    body += '\n\n'.join(rows) + f'\n\nOrder total: {inr(total)}\n\nPlease confirm the expected delivery date.\n'
    return subject, body
