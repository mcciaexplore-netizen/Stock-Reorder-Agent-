"""
config.py — Reorder Agent configuration
Copy .env.example → .env and fill in values before running.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Groq (free LLM) ──────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL:   str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Gmail SMTP (free email) ──────────────────────────────────
GMAIL_USER:         str = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")

# ── File paths ───────────────────────────────────────────────
INVENTORY_PATH = Path(os.getenv("INVENTORY_PATH", "inventory.xlsx"))
LOG_PATH       = Path(os.getenv("LOG_PATH",       "purchase_orders_log.csv"))

# ── Behaviour ────────────────────────────────────────────────
BUSINESS_NAME:    str  = os.getenv("BUSINESS_NAME",    "Your Company")
BUSINESS_ADDRESS: str  = os.getenv("BUSINESS_ADDRESS", "")   # optional, appears in PO header

# DRY_RUN=true  → previews POs in terminal, does NOT send emails
# DRY_RUN=false → sends PO emails via Gmail
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
