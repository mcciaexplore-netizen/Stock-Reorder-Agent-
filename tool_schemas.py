"""
tool_schemas.py
Tool definitions in Groq / OpenAI format.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_inventory",
            "description": (
                "Read all rows from the inventory Excel file. "
                "Returns every item as a JSON list with normalised column names. "
                "Always call this first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xlsx_path": {
                        "type": "string",
                        "description": "Path to the inventory Excel file.",
                    }
                },
                "required": ["xlsx_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_low_stock",
            "description": (
                "Filter the inventory to items where current stock is below "
                "the reorder level. Returns each low-stock item with a "
                "`shortage` field (reorder_level minus current_stock) and "
                "`reorder_qty` (how many to order). "
                "Results are grouped ready for PO drafting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inventory_json": {
                        "type": "string",
                        "description": "JSON string returned by read_inventory.",
                    }
                },
                "required": ["inventory_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_and_approve",
            "description": (
                "Show the drafted Purchase Order to the operator in the terminal "
                "and wait for approval (y / n / edit) before sending. "
                "ALWAYS call this before send_email. "
                "Returns approved=true/false and the final subject and body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_name":  {"type": "string"},
                    "supplier_email": {"type": "string"},
                    "po_number":      {"type": "string", "description": "e.g. PO-20250707-001"},
                    "items_json": {
                        "type": "string",
                        "description": (
                            "JSON array of items in this PO. Each item must have: "
                            "item_name, item_code, reorder_qty, unit, unit_price, line_total."
                        ),
                    },
                    "subject": {"type": "string"},
                    "body":    {"type": "string", "description": "Full PO email body, plain text."},
                },
                "required": [
                    "supplier_name", "supplier_email", "po_number",
                    "items_json", "subject", "body",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send the Purchase Order email via Gmail SMTP. "
                "Only call after preview_and_approve returns approved=true. "
                "Use the subject and body from the approval result exactly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to_email": {"type": "string"},
                    "subject":  {"type": "string"},
                    "body":     {"type": "string"},
                },
                "required": ["to_email", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_po_sent",
            "description": (
                "Append a record of the sent PO to the CSV log. "
                "Call this after every successful send_email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "po_number":      {"type": "string"},
                    "supplier_name":  {"type": "string"},
                    "supplier_email": {"type": "string"},
                    "items_count":    {"type": "integer", "description": "Number of line items in this PO."},
                    "total_value":    {"type": "string", "description": "Grand total as string e.g. '26000'."},
                },
                "required": ["po_number", "supplier_name", "supplier_email", "items_count", "total_value"],
            },
        },
    },
]
