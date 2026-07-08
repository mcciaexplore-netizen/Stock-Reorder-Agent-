import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import config
import tools
from po_utils import build_po_email, group_low_stock_items, po_number
from tools import find_low_stock, log_po_sent, read_inventory, send_email


st.set_page_config(page_title="Reorder Agent", page_icon="RA", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; max-width: 1280px; }
    [data-testid="stMetricValue"] { font-size: 1.7rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 6px; }
    .status-ok { color: #0f766e; font-weight: 600; }
    .status-warn { color: #b45309; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_inventory(path: Path) -> tuple[dict | None, str | None]:
    raw = read_inventory(str(path))
    data = json.loads(raw)
    if data.get("status") != "ok":
        return None, data.get("message", "Unable to read inventory.")
    low = json.loads(find_low_stock(json.dumps(data)))
    if low.get("status") != "ok":
        return None, low.get("message", "Unable to find low-stock items.")
    return {"inventory": data, "low_stock": low}, None


def save_upload(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix or ".xlsx"
    path = Path(tempfile.gettempdir()) / f"reorder_agent_upload{suffix}"
    path.write_bytes(uploaded_file.getvalue())
    return path


def money(value) -> str:
    return tools._inr(value)


st.title("Reorder Agent")

with st.sidebar:
    st.header("Controls")
    uploaded = st.file_uploader("Inventory file", type=["xlsx"])
    dry_run = st.toggle("Dry run", value=config.DRY_RUN)
    live_confirm = st.checkbox("Allow live email sending", disabled=dry_run)
    st.divider()
    st.caption(f"Business: {config.BUSINESS_NAME}")
    st.caption(f"Log: {config.LOG_PATH}")

source_path = save_upload(uploaded) if uploaded else Path(config.INVENTORY_PATH)

if not source_path.exists():
    st.error(f"Inventory file not found: {source_path}")
    st.stop()

payload, error = load_inventory(source_path)
if error:
    st.error(error)
    st.stop()

inventory = payload["inventory"]
low_stock = payload["low_stock"]
low_items = low_stock.get("low_stock_items", [])
suppliers = group_low_stock_items(low_items)
total_value = sum(s["total_value"] for s in suppliers)

top = st.columns(4)
top[0].metric("Inventory Items", inventory.get("count", 0))
top[1].metric("Low Stock", low_stock.get("low_stock_count", 0))
top[2].metric("Suppliers", len(suppliers))
top[3].metric("Order Value", money(total_value))

if not low_items:
    st.success("All items are well-stocked.")
    st.stop()

st.subheader("Low Stock")
low_df = pd.DataFrame(low_items)
visible_cols = [
    "item_name", "item_code", "current_stock", "reorder_level",
    "shortage", "reorder_qty", "unit", "supplier_name", "unit_price", "line_total",
]
st.dataframe(low_df[[c for c in visible_cols if c in low_df.columns]], width="stretch")

st.subheader("Purchase Orders")

if "po_status" not in st.session_state:
    st.session_state.po_status = {}

tabs = st.tabs([s["supplier_name"] for s in suppliers])

for index, (tab, supplier) in enumerate(zip(tabs, suppliers), start=1):
    number = po_number(index)
    default_subject, default_body = build_po_email(supplier, number)
    status_key = number

    with tab:
        head = st.columns([2, 1, 1])
        head[0].markdown(f"**{supplier['supplier_name']}**")
        head[1].markdown(f"**{supplier['items_count']} items**")
        head[2].markdown(f"**{money(supplier['total_value'])}**")

        item_df = pd.DataFrame(supplier["items"])
        st.dataframe(
            item_df[[c for c in visible_cols if c in item_df.columns]],
            width="stretch",
            hide_index=True,
        )

        subject = st.text_input("Subject", default_subject, key=f"subject_{number}")
        body = st.text_area("Email body", default_body, height=360, key=f"body_{number}")

        current_status = st.session_state.po_status.get(status_key, "pending")
        action_cols = st.columns([1, 1, 3])
        send_label = "Run dry send" if dry_run else "Send email"
        can_send = current_status == "pending" and (dry_run or live_confirm)

        if action_cols[0].button(send_label, key=f"send_{number}", disabled=not can_send):
            tools.DRY_RUN = dry_run
            result = json.loads(send_email(supplier["supplier_email"], subject, body))
            if result.get("status") == "ok":
                if dry_run:
                    st.session_state.po_status[status_key] = "dry_run"
                    st.toast(f"Dry run complete: {number}")
                else:
                    log_result = json.loads(log_po_sent(
                        number,
                        supplier["supplier_name"],
                        supplier["supplier_email"],
                        supplier["items_count"],
                        str(supplier["total_value"]),
                    ))
                    if log_result.get("status") == "ok":
                        st.session_state.po_status[status_key] = "sent"
                        st.toast(f"Sent and logged: {number}")
                    else:
                        st.session_state.po_status[status_key] = "send_failed"
                        st.error(log_result.get("message", "Email sent, but logging failed."))
            else:
                st.session_state.po_status[status_key] = "send_failed"
                st.error(result.get("message", "Unable to send email."))
            st.rerun()

        if action_cols[1].button("Skip", key=f"skip_{number}", disabled=current_status != "pending"):
            st.session_state.po_status[status_key] = "skipped"
            st.rerun()

        status = st.session_state.po_status.get(status_key, "pending")
        if status == "pending":
            action_cols[2].warning("Pending")
        elif status == "dry_run":
            action_cols[2].success("Dry run complete")
        elif status == "sent":
            action_cols[2].success("Sent")
        elif status == "skipped":
            action_cols[2].info("Skipped")
        else:
            action_cols[2].error("Needs attention")

if not dry_run and not live_confirm:
    st.warning("Live email sending is off until confirmed in the sidebar.")
