from __future__ import annotations

from datetime import date
from itertools import groupby
from operator import itemgetter

from config import BUSINESS_ADDRESS, BUSINESS_NAME, GMAIL_USER
from tools import _inr


def po_number(index: int, today: date | None = None) -> str:
    day = today or date.today()
    return f"PO-{day.strftime('%Y%m%d')}-{index:03d}"


def group_low_stock_items(items: list[dict]) -> list[dict]:
    sorted_items = sorted(items, key=lambda i: i.get("supplier_name", "Unknown Supplier"))
    groups: list[dict] = []
    for supplier_name, rows in groupby(sorted_items, key=itemgetter("supplier_name")):
        supplier_items = list(rows)
        groups.append({
            "supplier_name": supplier_name or "Unknown Supplier",
            "supplier_email": supplier_items[0].get("supplier_email", ""),
            "items": supplier_items,
            "items_count": len(supplier_items),
            "total_value": round(sum(float(i.get("line_total", 0)) for i in supplier_items), 2),
        })
    return groups


def build_po_email(supplier: dict, number: str, today: date | None = None) -> tuple[str, str]:
    day = today or date.today()
    supplier_name = supplier["supplier_name"]
    items = supplier["items"]
    subject = f"Purchase Order {number} - {supplier_name}"
    from_lines = BUSINESS_NAME
    if BUSINESS_ADDRESS:
        from_lines = f"{BUSINESS_NAME},\n              {BUSINESS_ADDRESS}"

    rows = []
    for item in items:
        rows.append(
            f"  {str(item.get('item_name', ''))[:23]:<24} "
            f"{str(item.get('item_code', ''))[:10]:<11} "
            f"{str(item.get('reorder_qty', ''))[:6]:>6} "
            f"{str(item.get('unit', ''))[:7]:<8} "
            f"{_inr(item.get('unit_price', 0)):>10} "
            f"{_inr(item.get('line_total', 0)):>11}"
        )

    grand_total = sum(float(i.get("line_total", 0)) for i in items)
    sender = GMAIL_USER or "the sender email"
    body = f"""Dear {supplier_name},

Please find our Purchase Order {number} below.
Kindly acknowledge and confirm the expected delivery date.

================================================
PURCHASE ORDER
PO Number : {number}
Date      : {day.strftime("%d %B %Y")}
From      : {from_lines}
================================================

ITEM                     CODE           QTY UNIT           RATE       TOTAL
------------------------------------------------
{chr(10).join(rows)}
------------------------------------------------
                                      GRAND TOTAL {_inr(grand_total):>11}
================================================

Please reply to this email to confirm the order.
For queries, contact us at {sender}.

Warm regards,
{BUSINESS_NAME}
"""
    return subject, body
