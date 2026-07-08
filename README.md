---
title: Stock Reorder Agent
emoji: 📦
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: "1.59.0"
app_file: streamlit_app.py
pinned: false
---

# Stock Reorder Agent

A Streamlit agent that scans inventory for low-stock items, drafts purchase orders, and emails suppliers.

## Features

- Reads inventory from `inventory.xlsx` and flags items below reorder threshold
- Groups low-stock items by supplier and drafts purchase order emails
- Sends PO emails via Gmail SMTP (or previews them in dry-run mode)
- Logs sent purchase orders to `purchase_orders_log.csv`
- Uses Groq (free LLM) for agent reasoning

## Run locally

**Prerequisites:** Python 3.11+

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` (or create `.env`) and fill in:
   - `GROQ_API_KEY` — free key from console.groq.com
   - `GROQ_MODEL` — defaults to `llama-3.3-70b-versatile`
   - `GMAIL_USER` / `GMAIL_APP_PASSWORD` — Gmail App Password for sending PO emails
   - `BUSINESS_NAME` / `BUSINESS_ADDRESS` — appear in the PO header
   - `DRY_RUN` — `true` to preview POs without sending email, `false` to send
3. Run the app:
   ```
   streamlit run streamlit_app.py
   ```

## Deploying on Hugging Face Spaces

Set the same environment variables listed above as **Space secrets** (Settings → Variables and secrets) — do not commit `.env`.
