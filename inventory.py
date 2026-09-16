"""Inventory import contracts and exact decimal quantities shared by every interface."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd


class ValidationError(ValueError):
    """An actionable business validation error that can be shown to an operator."""


ALIASES = {
    'item name': 'item_name', 'item': 'item_name', 'product': 'item_name',
    'product name': 'item_name', 'description': 'item_name', 'material': 'item_name',
    'item code': 'item_code', 'sku': 'item_code', 'code': 'item_code',
    'part no': 'item_code', 'part number': 'item_code',
    'current stock': 'current_stock', 'stock': 'current_stock', 'quantity': 'current_stock',
    'qty in hand': 'current_stock', 'qty on hand': 'current_stock',
    'closing stock': 'current_stock', 'bal qty': 'current_stock',
    'reorder level': 'reorder_level', 'reorder point': 'reorder_level',
    'min stock': 'reorder_level', 'minimum stock': 'reorder_level',
    'reorder qty': 'reorder_qty', 'reorder quantity': 'reorder_qty',
    'order qty': 'reorder_qty', 'order quantity': 'reorder_qty',
    'unit': 'unit', 'uom': 'unit', 'unit of measure': 'unit',
    'supplier': 'supplier_name', 'supplier name': 'supplier_name',
    'vendor': 'supplier_name', 'vendor name': 'supplier_name',
    'supplier email': 'supplier_email', 'vendor email': 'supplier_email', 'email': 'supplier_email',
    'unit price': 'unit_price', 'purchase price': 'unit_price',
    'price': 'unit_price', 'rate': 'unit_price', 'cost': 'unit_price',
    'category': 'category', 'group': 'category', 'type': 'category',
    'selling price': 'selling_price', 'barcode': 'barcode',
}
FIELDS = ('item_code', 'item_name', 'current_stock', 'reorder_level', 'reorder_qty',
          'unit', 'supplier_name', 'supplier_email', 'unit_price', 'category',
          'selling_price', 'barcode')
REQUIRED = {'item_code', 'item_name', 'current_stock', 'reorder_level', 'unit', 'unit_price'}
MAX_UNITS = 10**12


def text(value, name='Value', *, required=False, limit=500):
    value = '' if value is None else str(value).strip()
    if required and not value:
        raise ValidationError(f'{name} is required.')
    if len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValidationError(f'{name} is too long or contains invalid characters.')
    return value


def email(value, *, required=False):
    value = text(value, 'Email', required=required, limit=254).lower()
    if value and not re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+', value):
        raise ValidationError('Enter one valid supplier email address.')
    return value


def scaled(value, name='Quantity', scale=1000, *, signed=False):
    """Convert to bounded integer milli-units or paise; never coerce invalid data to zero."""
    raw = text(value, name, required=True, limit=80).replace('₹', '').strip()
    if ',' in raw:
        if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?', raw):
            raise ValidationError(f'{name} has invalid digit grouping.')
        raw = raw.replace(',', '')
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise ValidationError(f'{name} must be a number.') from None
    if not number.is_finite() or abs(number) > Decimal(MAX_UNITS) / scale:
        raise ValidationError(f'{name} is outside the supported range.')
    if not signed and number < 0:
        raise ValidationError(f'{name} cannot be negative.')
    units = number * scale
    if units != units.to_integral_value():
        places = 2 if scale == 100 else 3
        raise ValidationError(f'{name} supports at most {places} decimal places.')
    return int(units)


def quantity(value):
    return format(Decimal(value) / 1000, 'f').rstrip('0').rstrip('.') if value % 1000 else str(value // 1000)


def amount(paise):
    return format(Decimal(paise) / 100, '.2f')


def line_value(qty, price):
    result = int((Decimal(qty) * price / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if abs(result) > MAX_UNITS:
        raise ValidationError('Line value exceeds the supported range.')
    return result


def inr(value):
    number = Decimal(str(value).replace(',', '')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    if not number.is_finite():
        raise ValidationError('Amount must be finite.')
    whole, fraction = format(abs(number), '.2f').split('.')
    tail, head = whole[-3:], whole[:-3]
    groups = []
    while head:
        groups.insert(0, head[-2:]); head = head[:-2]
    whole = ','.join(groups + [tail])
    return f'{"-" if number < 0 else ""}₹{whole}.{fraction}'


def normalize_header(value):
    key = str(value).strip().lower().replace('_', ' ')
    return ALIASES.get(key, key.replace(' ', '_'))


def load_table(source, filename=None):
    name = filename or str(source)
    try:
        if name.lower().endswith('.csv'):
            return pd.read_csv(source, dtype=str, keep_default_na=False)
        if name.lower().endswith('.xlsx'):
            return pd.read_excel(source, dtype=str, keep_default_na=False)
        raise ValidationError('Choose an .xlsx or .csv file.')
    except (ValueError, OSError, ImportError) as exc:
        raise ValidationError(f'Unable to read inventory: {exc}') from exc


def validate_table(frame, mapping=None):
    """Return a complete preview and row errors. Callers must reject the entire import on error."""
    renamed = [mapping.get(str(c), normalize_header(c)) if mapping else normalize_header(c) for c in frame.columns]
    active = [c for c in renamed if c in FIELDS]
    errors = []
    duplicates = {c for c in active if active.count(c) > 1}
    if duplicates:
        errors.append('Multiple columns map to: ' + ', '.join(sorted(duplicates)))
    missing = REQUIRED - set(active)
    if missing:
        errors.append('Missing required columns: ' + ', '.join(sorted(missing)))
    if errors:
        return [], errors
    frame = frame.copy().fillna(''); frame.columns = renamed
    records = []; seen = set(); barcodes = set()
    for row_no, raw in enumerate(frame.to_dict('records'), 2):
        if not any(str(v).strip() for v in raw.values()):
            continue
        try:
            for numeric_field in ('current_stock', 'reorder_level', 'unit_price'):
                if not str(raw.get(numeric_field, '')).strip():
                    raise ValidationError(f'{numeric_field.replace("_", " ").title()} is required.')
            record = validate_product(raw)
            record['current_stock'] = quantity(scaled(raw.get('current_stock'), 'Current stock'))
            code = record['item_code'].casefold()
            if code in seen:
                raise ValidationError(f'Duplicate SKU: {record["item_code"]}')
            seen.add(code)
            if record['barcode']:
                if record['barcode'].casefold() in barcodes:
                    raise ValidationError('Duplicate barcode.')
                barcodes.add(record['barcode'].casefold())
            records.append(record)
        except ValidationError as exc:
            errors.append(f'Row {row_no}: {exc}')
    if not records and not errors:
        errors.append('The file has no inventory rows.')
    return records, errors


def validate_product(raw):
    result = {k: text(raw.get(k, ''), k.replace('_', ' ').title(), limit=200)
              for k in ('item_code', 'item_name', 'unit', 'category', 'barcode', 'supplier_name')}
    for field in ('item_code', 'item_name', 'unit'):
        if not result[field]:
            raise ValidationError(f'{field.replace("_", " ").title()} is required.')
    result['supplier_email'] = email(raw.get('supplier_email', ''))
    if result['supplier_email'] and not result['supplier_name']:
        raise ValidationError('Supplier name is required when supplier email is supplied.')
    for key in ('reorder_level', 'reorder_qty'):
        value = raw.get(key, 0)
        result[key] = quantity(scaled((value or 0) if key == 'reorder_qty' else value, key.replace('_', ' ').title()))
    for key in ('unit_price', 'selling_price'):
        value = raw.get(key, 0)
        result[key] = amount(scaled((value or 0) if key == 'selling_price' else value, key.replace('_', ' ').title(), 100))
    return result


def csv_bytes(rows, fields=None):
    """Protect text fields from spreadsheet formula execution when opened in Excel."""
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v)
                for k, v in row.items()}
        writer.writerow(safe)
    return stream.getvalue().encode('utf-8-sig')
