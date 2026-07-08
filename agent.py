#!/usr/bin/env python3
"""
agent.py — Reorder Agent
─────────────────────────────────────────────────────────────
LLM  : Groq API — llama-3.3-70b-versatile (free tier)
Email: Gmail SMTP (free)
Data : Local inventory Excel + CSV log

What it does:
  1. Reads your inventory.xlsx
  2. Finds items below their reorder level
  3. Groups them by supplier
  4. Drafts one Purchase Order per supplier
  5. You approve each PO in the terminal
  6. Approved POs are emailed to suppliers
  7. Everything is logged to purchase_orders_log.csv

Usage:
  python agent.py                            # default file
  python agent.py --file my_inventory.xlsx   # custom file
  python agent.py --no-dry-run              # actually send emails
"""

import argparse
import json
import sys
from datetime import date

from groq import Groq

from config import (
    GROQ_API_KEY, GROQ_MODEL, BUSINESS_NAME,
    BUSINESS_ADDRESS, DRY_RUN, INVENTORY_PATH,
)
from tool_schemas import TOOL_SCHEMAS
from tools import (
    find_low_stock, log_po_sent,
    preview_and_approve, read_inventory, send_email,
)

# ─────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────

TODAY = date.today().strftime("%d %B %Y")

SYSTEM_PROMPT = f"""You are a reorder agent for {BUSINESS_NAME}.
Today's date: {TODAY}

Your job — follow these steps exactly:

1. Call read_inventory with the provided file path.
2. Call find_low_stock on the result.
3. If low_stock_count is 0, report "All items are well-stocked." and stop.
4. Review the supplier_summary returned — each entry is one Purchase Order to send.
5. For each supplier in the summary:
   a. Collect all low_stock_items for that supplier.
   b. Generate a PO number: PO-{date.today().strftime("%Y%m%d")}-001 for the first PO,
      PO-{date.today().strftime("%Y%m%d")}-002 for the second, etc.
   c. Calculate line_total for each item (reorder_qty × unit_price).
   d. Draft the Purchase Order email using the template below.
   e. Call preview_and_approve — NEVER skip this.
   f. If approved=true: call send_email using the subject and body
      returned by preview_and_approve (operator may have edited them).
   g. Call log_po_sent after every successful send.
6. After all POs, print a summary: POs sent, POs skipped, total order value.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PO EMAIL TEMPLATE — use this structure exactly:

Subject:
  Purchase Order [PO-NUMBER] — [Supplier Name]

Body:
  Dear [Supplier Name],

  Please find our Purchase Order [PO-NUMBER] below.
  Kindly acknowledge and confirm the expected delivery date.

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PURCHASE ORDER
  PO Number : [PO-NUMBER]
  Date      : {TODAY}
  From      : {BUSINESS_NAME}{"," + chr(10) + "              " + BUSINESS_ADDRESS if BUSINESS_ADDRESS else ""}
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ITEM                     CODE         QTY    UNIT    RATE        TOTAL
  [item name padded]       [code]       [qty]  [unit]  ₹[price]   ₹[total]
  ... (one row per item)
                                               ───────────────────────────
                                    GRAND TOTAL            ₹[grand_total]
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Please reply to this email to confirm the order.
  For queries, contact us at [sender email].

  Warm regards,
  {BUSINESS_NAME}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULES:
- Pass items_json as a JSON array to preview_and_approve — each item must
  include: item_name, item_code, reorder_qty, unit, unit_price, line_total
- Use ₹ with Indian number formatting in the email body
- Plain text only — no markdown, no asterisks
- Align the PO table with spaces so it looks neat in a fixed-width font
- One PO per supplier — do NOT split a supplier's items across multiple POs
"""

# ─────────────────────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────────────────────

def run_tool(name: str, inputs: dict) -> str:
    dispatch = {
        "read_inventory":    lambda i: read_inventory(i["xlsx_path"]),
        "find_low_stock":    lambda i: find_low_stock(i["inventory_json"]),
        "preview_and_approve": lambda i: preview_and_approve(
            i["supplier_name"], i["supplier_email"], i["po_number"],
            i["items_json"], i["subject"], i["body"],
        ),
        "send_email":   lambda i: send_email(i["to_email"], i["subject"], i["body"]),
        "log_po_sent":  lambda i: log_po_sent(
            i["po_number"], i["supplier_name"], i["supplier_email"],
            int(i["items_count"]), str(i["total_value"]),
        ),
    }
    fn = dispatch.get(name)
    if not fn:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})
    return fn(inputs)


# ─────────────────────────────────────────────────────────────
# Agentic loop
# ─────────────────────────────────────────────────────────────

def run_agent(xlsx_path: str) -> None:
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set. Get a free key at console.groq.com")
        sys.exit(1)

    client = Groq(api_key=GROQ_API_KEY)

    print(f"\n{'─' * 62}")
    print(f"  Reorder Agent  —  {BUSINESS_NAME}")
    print(f"  LLM   : {GROQ_MODEL}  (Groq free tier)")
    print(f"  File  : {xlsx_path}")
    print(f"  Date  : {TODAY}")
    print(f"  Mode  : {'DRY RUN — no emails sent' if DRY_RUN else 'LIVE — emails WILL be sent'}")
    print(f"{'─' * 62}\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Check the inventory in '{xlsx_path}', find all items below "
                f"their reorder level, and send Purchase Orders to suppliers."
            ),
        },
    ]

    MAX_ITER = 50   # more than payment agent — multiple POs needed
    approved_messages: set[tuple[str, str]] = set()
    sent_po_numbers: set[str] = set()

    for _ in range(MAX_ITER):
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.1,
        )

        msg    = response.choices[0].message
        finish = response.choices[0].finish_reason

        # Print agent reasoning / commentary
        if msg.content and msg.content.strip():
            print(f"\n[Agent] {msg.content.strip()}\n")

        # Build assistant history entry
        assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_entry)

        if finish == "stop" or not msg.tool_calls:
            break

        # Execute tools
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            arg_str = ", ".join(f"{k}={repr(v)[:45]}" for k, v in fn_args.items())
            print(f"  → {fn_name}({arg_str})")

            if fn_name == "send_email":
                approval_key = (fn_args.get("to_email", ""), fn_args.get("subject", ""))
                if approval_key not in approved_messages:
                    result_str = json.dumps({
                        "status": "error",
                        "message": "Blocked: PO email was not approved by the operator.",
                    })
                else:
                    result_str = run_tool(fn_name, fn_args)
            elif fn_name == "log_po_sent":
                if DRY_RUN:
                    result_str = json.dumps({
                        "status": "ok",
                        "logged": False,
                        "message": "Skipped log in dry-run mode.",
                    })
                elif fn_args.get("po_number") not in sent_po_numbers:
                    result_str = json.dumps({
                        "status": "error",
                        "message": "Blocked: PO was not successfully sent.",
                    })
                else:
                    result_str = run_tool(fn_name, fn_args)
            else:
                result_str = run_tool(fn_name, fn_args)

            try:
                r = json.loads(result_str)
                if r.get("status") == "error":
                    print(f"  [ERROR] {r['message']}")
                elif fn_name == "preview_and_approve" and r.get("approved") is True:
                    approved_messages.add((
                        fn_args.get("supplier_email", ""),
                        r.get("subject", fn_args.get("subject", "")),
                    ))
                elif fn_name == "send_email" and r.get("status") == "ok" and r.get("mode") != "dry_run":
                    subject = fn_args.get("subject", "")
                    marker = "Purchase Order "
                    if marker in subject:
                        sent_po_numbers.add(subject.split(marker, 1)[1].split(" ", 1)[0])
            except Exception:
                pass

            messages.append({
                "role": "tool", "tool_call_id": tc.id, "content": result_str,
            })
    else:
        print(f"[Agent] Reached iteration limit. Stopping.")

    print(f"\n{'─' * 62}")
    print("  Agent finished.")
    print(f"{'─' * 62}\n")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reorder Agent — sends Purchase Orders for low-stock items (Groq + Gmail, free tier)"
    )
    parser.add_argument(
        "--file", "-f",
        default=str(INVENTORY_PATH),
        help=f"Path to inventory Excel (default: {INVENTORY_PATH})",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually send emails (overrides DRY_RUN=true in .env)",
    )
    args = parser.parse_args()

    if args.no_dry_run:
        import config, tools
        config.DRY_RUN = False
        tools.DRY_RUN  = False

    run_agent(args.file)


if __name__ == "__main__":
    main()
