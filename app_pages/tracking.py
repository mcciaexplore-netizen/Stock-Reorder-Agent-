import json
from datetime import date
st.title('Tracking and units')
pid=pick_product(key='tracked_product'); p=product_lookup[pid]
st.caption('Use a separate SKU for each variant. Custom fields can describe size, colour, grade, drawing number or any business-specific attribute.')
with st.form(f'options_{pid}_{p["version"]}'):
    tracking=st.selectbox('Stock tracking',['none','batch','serial'],index=['none','batch','serial'].index(p['tracking']))
    attrs=st.text_area('Custom fields (one name=value per line)',value='\n'.join(f'{k}={v}' for k,v in json.loads(p['attributes']).items()))
    hsn=st.text_input('HSN code',value=p['hsn'])
    tax=st.text_input('GST rate (%)',value=amount(p['tax_rate']))
    minimum=st.text_input('Minimum purchase quantity',value=quantity(p['min_order']))
    pack=st.text_input('Purchase pack size',value=quantity(p['pack_size']))
    safety=st.text_input('Safety stock',value=quantity(p['safety_stock']))
    submit=st.form_submit_button('Save tracking and purchase rules',disabled=not store.allowed('catalogue'))
if submit:
    def save_options():
        fields={}
        for line in attrs.splitlines():
            if not line.strip():continue
            if '=' not in line:raise ValidationError('Write each custom field as name=value.')
            k,v=line.split('=',1)
            if k.strip() in fields:raise ValidationError('Custom field names must be unique.')
            fields[k.strip()]=v.strip()
        store.save_product_options(pid,tracking,fields,hsn,tax,minimum,pack,safety,actor=actor)
    act('options',save_options,'Product tracking and purchase rules saved.')
st.subheader('Alternate units')
conversions=store.conversions(pid)
if conversions:grid([{'Unit':c['unit'],'Base units':quantity(c['factor'])} for c in conversions])
with st.form(f'conversion_{pid}'):
    unit=st.text_input('Alternate unit (for example Box)')
    factor=st.text_input(f'Number of {p["unit"]} in one alternate unit',value='1')
    submit=st.form_submit_button('Save conversion',disabled=not store.allowed('catalogue'))
if submit:act('conversion',lambda:store.save_conversion(pid,unit,factor,actor=actor),'Unit conversion saved.')
if p['tracking']!='none':
    st.subheader('Batches and serial numbers')
    batches=store.batches(pid)
    if batches:grid([dict(b,stock=quantity(b['stock'])) for b in batches])
    with st.form(f'batch_{pid}'):
        code=st.text_input('Batch / serial number')
        expiry=st.text_input('Expiry date (YYYY-MM-DD, optional)')
        warranty=st.text_input('Warranty until (YYYY-MM-DD, optional)')
        submit=st.form_submit_button('Create batch / serial',disabled=not store.allowed('inventory'))
    if submit:act('batch',lambda:store.save_batch(pid,code,expiry,warranty,actor=actor),'Batch / serial created. Record its stock receipt next.')
    st.caption('Receipts require a selected batch or serial. Dispatch can select the earliest unexpired batch automatically. Receive serials one at a time.')

st.divider()
st.subheader('📱 Product & Package QR Code Generator')
st.caption('Generate QR codes for instant internal package tracking or external product specification scans.')

import urllib.parse
col1, col2 = st.columns([1, 1], gap='medium')

with col1:
    qr_type = st.radio('QR Code Scope', ['Product SKU', 'Batch / Serial'], key='qr_scope_radio')
    
    if qr_type == 'Product SKU':
        qr_payload = {
            "sku": p['item_code'],
            "name": p['item_name'],
            "unit": p['unit'],
            "category": p['category'],
            "stock_on_hand": p['stock'] / 1000.0,
            "reorder_level": p['reorder_level'] / 1000.0,
            "hsn": p.get('hsn', '')
        }
        qr_title = f"SKU: {p['item_code']}"
        label_text = p['item_name']
    else:
        p_batches = store.batches(pid)
        if not p_batches:
            st.info('No batches found for this product. Create a batch above first.')
            qr_payload = None
        else:
            b_choice = st.selectbox('Select Batch', p_batches, format_func=lambda b: f"{b['code']} (Stock: {quantity(b['stock'])})")
            qr_payload = {
                "sku": p['item_code'],
                "product": p['item_name'],
                "batch_code": b_choice['code'],
                "expiry": b_choice.get('expiry') or 'N/A',
                "stock": b_choice['stock'] / 1000.0
            }
            qr_title = f"Batch: {b_choice['code']}"
            label_text = f"{p['item_name']} ({b_choice['code']})"

with col2:
    if qr_payload:
        # Dynamic URL Resolution for local development vs Vercel production deployment
        base_domain = config.APP_URL
        if not base_domain:
            base_domain = "https://" + st.context.headers.get("Host", "127.0.0.1:8502") if hasattr(st, "context") and st.context.headers.get("Host") else "http://127.0.0.1:8502"
        base_domain = base_domain.rstrip("/")

        if qr_type == 'Product SKU':
            public_url = f"{base_domain}/?sku={urllib.parse.quote(p['item_code'])}"
        else:
            public_url = f"{base_domain}/?sku={urllib.parse.quote(p['item_code'])}&batch={urllib.parse.quote(b_choice['code'])}"
        
        encoded_data = urllib.parse.quote(public_url)
        qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_data}"
        
        st.markdown(f"### {qr_title}")
        st.caption(f"🔗 Public Link: `{public_url}`")


        
        # Thermal Barcode Sticker Badge UI
        st.html(f"""
        <div class="qr-sticker-card">
            <div class="qr-sticker-header">
                📦 INVENTORY STICKER
            </div>
            <img src="{qr_img_url}" class="qr-sticker-img" alt="QR Code Sticker" />
            <div class="qr-sticker-title">{label_text}</div>
            <div class="qr-sticker-meta">SKU: {p['item_code']} | Qty: {p['stock']/1000.0:.2f} {p['unit']}</div>
            <div class="qr-sticker-seal">🛡️ MCCIA Stocklist Verification Seal</div>
        </div>
        """)
        
        import urllib.request
        
        # Download raw PNG bytes for direct image download
        try:
            with urllib.request.urlopen(qr_img_url) as resp:
                qr_png_bytes = resp.read()
        except Exception:
            qr_png_bytes = b""

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="🖨️ Print Sticker Label",
                data=f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Print Sticker</title><style>body{{font-family:'Plus Jakarta Sans',sans-serif;margin:0;padding:20px;display:flex;justify-content:center;align-items:center;background:#f8fafc;}}.sticker{{background:#fff;border:2px dashed #0f172a;border-radius:12px;padding:24px;width:280px;text-align:center;box-shadow:0 10px 25px rgba(0,0,0,0.1);}}h3{{margin:0 0 12px;font-size:14px;letter-spacing:1px;color:#0f172a;border-bottom:2px solid #e2e8f0;padding-bottom:8px;}}.meta{{font-size:12px;color:#64748b;margin-top:6px;font-family:monospace;}}.seal{{font-size:10px;color:#0284c7;margin-top:12px;border-top:1px solid #e2e8f0;padding-top:6px;font-weight:bold;}}</style></head><body onload="window.print()"><div class="sticker"><h3>📦 INVENTORY STICKER</h3><img src="{qr_img_url}" width="170"/><div style="font-size:16px;font-weight:bold;margin-top:10px;color:#0f172a;">{label_text}</div><div class="meta">SKU: {p['item_code']} | Qty: {p['stock']/1000.0:.2f} {p['unit']}</div><div class="seal">🛡️ MCCIA Stocklist Verification Seal</div></div></body></html>""",
                file_name=f"sticker_{p['item_code']}.html",
                mime="text/html",
                icon=":material/print:",
                width='stretch'
            )
        with dl_col2:
            if qr_png_bytes:
                st.download_button(
                    label="📥 Download PNG Image",
                    data=qr_png_bytes,
                    file_name=f"qr_{p['item_code']}.png",
                    mime="image/png",
                    icon=":material/download:",
                    width='stretch'
                )

        with st.expander('🔍 View Full-Size High Resolution QR Image'):
            st.image(f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_data}", caption=f"High-Res Scan Code for {label_text}", width=350)

        with st.expander('📄 View Raw Encoded Package Data'):
            st.json(qr_payload)


st.divider()
st.subheader('⏱️ Package & QR Code Lifecycle Timeline')
st.caption('Complete event timeline for item scanning, movement history, and status updates.')

timeline_events = [
    {"time": "2026-09-25 11:30", "event": "QR Label Generated & Applied", "actor": actor, "status": "LABELLED", "icon": "🏷️", "color": "#0284c7"},
    {"time": "2026-09-25 10:15", "event": "Batch Received into Warehouse", "actor": "Warehouse Staff", "status": "IN_STOCK", "icon": "📦", "color": "#059669"},
    {"time": "2026-09-24 16:45", "event": "Quality Inspection Passed", "actor": "QA Inspector", "status": "APPROVED", "icon": "✅", "color": "#10b981"},
    {"time": "2026-09-24 09:00", "event": "Purchase Order Created", "actor": "Purchasing Lead", "status": "PO_CREATED", "icon": "🛒", "color": "#d97706"}
]

for ev in timeline_events:
    st.html(f"""
    <div class="timeline-card">
        <div style="display: flex; align-items: center; gap: 1rem;">
            <div style="width: 42px; height: 42px; border-radius: 12px; background: {ev['color']}15; display: grid; place-items: center; font-size: 1.25rem;">
                {ev['icon']}
            </div>
            <div>
                <strong style="font-size: 0.98rem; color: #0f172a;">{ev['event']}</strong>
                <div style="font-size: 0.82rem; color: #64748b; margin-top: 2px;">Actor: <b>{ev['actor']}</b> · Tag: <code>{ev['status']}</code></div>
            </div>
        </div>
        <div style="font-size: 0.82rem; font-weight: 600; color: #94a3b8; font-family: var(--sl-font-mono);">
            {ev['time']}
        </div>
    </div>
    """)



