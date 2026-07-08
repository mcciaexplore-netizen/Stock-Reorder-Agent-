"""
tools.py — Reorder Agent tool implementations
No AI here — plain Python doing the actual work.
The agentic loop in agent.py dispatches Groq tool calls here.
"""

import csv
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

from config import GMAIL_USER, GMAIL_APP_PASSWORD, LOG_PATH, DRY_RUN

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _ok(payload: dict) -> str:
    return json.dumps({"status": "ok", **payload})

def _err(message: str) -> str:
    return json.dumps({"status": "error", "message": message})

def _inr(amount) -> str:
    """Format number as Indian ₹ string: 145000 → ₹1,45,000"""
    try:
        n = int(float(str(amount).replace(",", "")))
        if n < 0:
            return f"-₹{_inr_pos(-n)}"
        return f"₹{_inr_pos(n)}"
    except Exception:
        return f"₹{amount}"

def _inr_pos(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    result = s[-3:]
    s = s[:-3]
    while s:
        result = s[-2:] + "," + result if len(s) >= 2 else s + "," + result
        s = s[:-2]
    return result


# ─────────────────────────────────────────────────────────────
# Tool 1 — read_inventory
# ─────────────────────────────────────────────────────────────

# Common column name variants MSMEs use — we normalise all of these
_COL_MAP = {
    # item name
    "item name": "item_name", "item": "item_name",
    "product name": "item_name", "product": "item_name",
    "description": "item_name", "material": "item_name",
    # item code
    "item code": "item_code", "sku": "item_code",
    "code": "item_code", "part no": "item_code",
    "part number": "item_code",
    # current stock
    "current stock": "current_stock", "stock": "current_stock",
    "qty in hand": "current_stock", "qty on hand": "current_stock",
    "quantity": "current_stock", "bal qty": "current_stock",
    "closing stock": "current_stock",
    # reorder level
    "reorder level": "reorder_level", "reorder point": "reorder_level",
    "min stock": "reorder_level", "minimum stock": "reorder_level",
    "safety stock": "reorder_level",
    # reorder quantity
    "reorder qty": "reorder_qty", "reorder quantity": "reorder_qty",
    "order qty": "reorder_qty", "order quantity": "reorder_qty",
    "min order qty": "reorder_qty",
    # unit
    "unit": "unit", "uom": "unit", "unit of measure": "unit",
    # supplier name
    "supplier name": "supplier_name", "supplier": "supplier_name",
    "vendor": "supplier_name", "vendor name": "supplier_name",
    # supplier email
    "supplier email": "supplier_email", "vendor email": "supplier_email",
    "email": "supplier_email",
    # unit price
    "unit price": "unit_price", "price": "unit_price",
    "rate": "unit_price", "cost": "unit_price",
    "purchase price": "unit_price",
    # category
    "category": "category", "group": "category", "type": "category",
}

def read_inventory(xlsx_path: str) -> str:
    path = Path(xlsx_path)
    if not path.exists():
        return _err(f"File not found: {xlsx_path}")
    try:
        df = pd.read_excel(path, dtype=str)

        # Normalise column names
        df.columns = [
            _COL_MAP.get(c.strip().lower(), c.strip().lower().replace(" ", "_"))
            for c in df.columns
        ]
        df = df.fillna("")

        # Convert numeric-looking columns to numbers
        for col in ["current_stock", "reorder_level", "reorder_qty", "unit_price"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        return _ok({"count": len(df), "items": df.to_dict(orient="records")})
    except Exception as exc:
        return _err(str(exc))


# ─────────────────────────────────────────────────────────────
# Tool 2 — find_low_stock
# ─────────────────────────────────────────────────────────────

def find_low_stock(inventory_json: str) -> str:
    """
    Return items where current_stock < reorder_level.
    Adds `shortage` and `line_total` to each record.
    Groups results by supplier for easier PO drafting.
    """
    try:
        data  = json.loads(inventory_json)
        items = data.get("items", []) if isinstance(data, dict) else data

        low: list[dict] = []
        for item in items:
            try:
                current  = float(item.get("current_stock", 0))
                reorder  = float(item.get("reorder_level", 0))
                qty      = float(item.get("reorder_qty", 0))
                price    = float(item.get("unit_price", 0))
            except (TypeError, ValueError):
                continue

            if current < reorder:
                record = dict(item)
                record["shortage"]   = round(reorder - current, 2)
                record["reorder_qty"] = qty if qty > 0 else round(reorder * 1.5 - current, 2)
                record["line_total"] = round(record["reorder_qty"] * price, 2)
                low.append(record)

        if not low:
            return _ok({"low_stock_count": 0, "low_stock_items": [],
                        "message": "All items are above reorder level."})

        # Group by supplier for summary
        suppliers: dict[str, list] = {}
        for item in low:
            sup = item.get("supplier_name", "Unknown Supplier")
            suppliers.setdefault(sup, []).append(item)

        supplier_summary = [
            {
                "supplier_name":  sup,
                "supplier_email": items[0].get("supplier_email", ""),
                "item_count":     len(items),
                "total_value":    round(sum(i["line_total"] for i in items), 2),
            }
            for sup, items in suppliers.items()
        ]

        return _ok({
            "low_stock_count":   len(low),
            "supplier_count":    len(suppliers),
            "low_stock_items":   low,
            "supplier_summary":  supplier_summary,
        })
    except Exception as exc:
        return _err(str(exc))


# ─────────────────────────────────────────────────────────────
# Tool 3 — preview_and_approve
# ─────────────────────────────────────────────────────────────

def preview_and_approve(
    supplier_name:  str,
    supplier_email: str,
    po_number:      str,
    items_json:     str,
    subject:        str,
    body:           str,
) -> str:
    div  = "═" * 62
    thin = "─" * 62

    try:
        items = json.loads(items_json)
    except json.JSONDecodeError:
        items = []

    grand_total = sum(
        float(str(i.get("line_total", 0)).replace(",", "")) for i in items
    )

    print(f"\n{div}")
    print(f"  PURCHASE ORDER DRAFT")
    print(thin)
    print(f"  Supplier  : {supplier_name}")
    print(f"  Email     : {supplier_email}")
    print(f"  PO Number : {po_number}")
    print(thin)
    print(f"  {'ITEM':<25} {'CODE':<12} {'QTY':>6} {'UNIT':<8} {'RATE':>10} {'TOTAL':>10}")
    print(thin)
    for item in items:
        print(
            f"  {str(item.get('item_name',''))[:24]:<25} "
            f"{str(item.get('item_code',''))[:11]:<12} "
            f"{str(item.get('reorder_qty',''))[:5]:>6} "
            f"{str(item.get('unit',''))[:7]:<8} "
            f"{_inr(item.get('unit_price', 0)):>10} "
            f"{_inr(item.get('line_total', 0)):>10}"
        )
    print(thin)
    print(f"  {'GRAND TOTAL':>55}  {_inr(grand_total):>10}")
    print(div)
    print(f"\n  Subject : {subject}")
    print(thin)
    print("  Email body preview (first 300 chars):")
    for line in body[:300].split("\n"):
        print(f"    {line}")
    if len(body) > 300:
        print("    ...")
    print(f"\n{div}")

    while True:
        choice = input("  Send this PO? [y = yes / n = skip / e = edit] : ").strip().lower()

        if choice == "y":
            return _ok({"approved": True, "subject": subject, "body": body})

        elif choice == "n":
            print("  Skipped.\n")
            return _ok({"approved": False, "reason": "Operator skipped"})

        elif choice == "e":
            print("  Edit subject (press ENTER to keep current):")
            new_subject = input(f"  [{subject}] > ").strip() or subject
            print("  Paste edited body (\\n for line breaks, ENTER when done):")
            new_body = input("  > ").replace("\\n", "\n").strip() or body
            if input("  Send edited version? [y/n] : ").strip().lower() == "y":
                return _ok({"approved": True, "subject": new_subject, "body": new_body})
            return _ok({"approved": False, "reason": "Operator cancelled after editing"})

        else:
            print("  Enter y, n, or e.")


# ─────────────────────────────────────────────────────────────
# Tool 4 — send_email
# ─────────────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, body: str) -> str:
    if DRY_RUN:
        print(f"\n  [DRY RUN] Would email → {to_email}")
        print(f"  Subject : {subject}\n")
        return _ok({"mode": "dry_run", "to": to_email})

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return _err("GMAIL_USER or GMAIL_APP_PASSWORD not set in .env")

    try:
        msg            = MIMEMultipart()
        msg["From"]    = GMAIL_USER
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                smtp.send_message(msg)
        except smtplib.SMTPException:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
                smtp.ehlo(); smtp.starttls()
                smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                smtp.send_message(msg)

        return _ok({"sent_to": to_email, "subject": subject})

    except Exception as exc:
        return _err(str(exc))


# ─────────────────────────────────────────────────────────────
# Tool 5 — log_po_sent
# ─────────────────────────────────────────────────────────────

_LOG_FIELDS = [
    "timestamp", "po_number", "supplier_name",
    "supplier_email", "items_count", "total_value",
]

def log_po_sent(
    po_number:      str,
    supplier_name:  str,
    supplier_email: str,
    items_count:    int,
    total_value:    str,
) -> str:
    try:
        log_path  = Path(LOG_PATH)
        new_file  = not log_path.exists() or log_path.stat().st_size == 0

        with open(log_path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({
                "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "po_number":      po_number,
                "supplier_name":  supplier_name,
                "supplier_email": supplier_email,
                "items_count":    items_count,
                "total_value":    total_value,
            })
        return _ok({"logged": po_number, "log_file": str(log_path)})
    except Exception as exc:
        return _err(str(exc))
