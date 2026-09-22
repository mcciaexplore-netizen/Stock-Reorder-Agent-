"""Stocklist local workspace. UI actions delegate all business rules to Stocklist."""
from __future__ import annotations

import hashlib
import io
import sqlite3
import json
import runpy
from pathlib import Path
from datetime import date
from uuid import uuid4

import pandas as pd
import streamlit as st

import config
from inventory import (FIELDS, ValidationError, amount, csv_bytes, inr, line_value,
                       load_table, normalize_header, quantity, validate_table)
from stocklist import Stocklist
from demo_access import demo_profiles
from frontend import (apply_brand, access_form, sidebar_brand, workspace_bar,
                      attention_summary, workspace_footer, PAGE_ICONS)


st.set_page_config(page_title='Stocklist | MCCIA', page_icon=':material/inventory_2:', layout='wide')
apply_brand()
store = Stocklist(config.DATABASE_PATH, session_token=st.session_state.get('auth_token'))
demo_accounts = demo_profiles(config.DATABASE_PATH, config.DEMO_ACCESS_PATH)
is_demo = bool(demo_accounts)
auth_content = st.empty()

if store.needs_setup():
    with auth_content.container():
        access = access_form(setup=True)
    if access['submitted']:
        try:
            if access['password'] != access['confirm']:
                raise ValidationError('Passwords do not match.')
            with access['feedback'].container(), st.spinner('Creating your owner account...'):
                st.session_state['auth_token'] = store.bootstrap(access['username'], access['name'], access['password'])
            auth_content.empty()
            st.rerun()
        except ValidationError as exc:
            access['feedback'].error(str(exc))
    st.stop()
try:
    identity = store.identity()
except ValidationError:
    with auth_content.container():
        access = access_form(demos=demo_accounts)
    if access['submitted'] or access['demo']:
        try:
            credentials = access['demo'] or access
            with access['feedback'].container(), st.spinner('Opening your workspace...'):
                token = store.login(credentials['username'], credentials['password'])
            st.session_state.clear()
            st.session_state['auth_token'] = token
            auth_content.empty()
            st.rerun()
        except ValidationError as exc:
            access['feedback'].error(str(exc))
    st.stop()
actor = identity['name']
business = store.settings()
sidebar_content = st.sidebar.empty()

@st.fragment(run_every='60s')
def maintenance_tick():
    try:
        store.refresh_alerts()
        if store.allowed('backup') and business.get('backup_enabled')=='true':
            store.run_maintenance(actor=actor)
    except (ValidationError, sqlite3.Error, OSError) as exc:
        st.warning(f'Background check needs attention: {exc}')

maintenance_tick()


def operation_key(scope):
    return st.session_state.setdefault('operation_' + scope, uuid4().hex)


def act(scope, fn, message):
    try:
        result = fn()
    except (ValidationError, sqlite3.OperationalError, OSError) as exc:
        st.error(str(exc))
        return
    st.session_state.pop('operation_' + scope, None)
    if scope.startswith('move_'):
        for state_key in list(st.session_state):
            if state_key.startswith('count_baseline_'):
                del st.session_state[state_key]
    st.session_state['notice'] = message(result) if callable(message) else message
    page_content.empty()
    st.rerun()


def grid(rows):
    frame = pd.DataFrame(rows)
    columns = {name: st.column_config.TextColumn(name, width='medium')
               for name in ('Product', 'Supplier', 'Customer') if name in frame.columns}
    st.dataframe(frame, hide_index=True, width='stretch', row_height=40,
                 height=min(max((len(frame) + 1) * 40 + 3, 120), 483), column_config=columns)


def stock_rows(products):
    return [{'SKU': p['item_code'], 'Product': p['item_name'], 'Category': p['category'],
             'Unit': p['unit'], 'On hand': quantity(p['stock']), 'Incoming': quantity(p['incoming']),
             'In drafts': quantity(p['planned']), 'Reorder level': quantity(p['reorder_level']),
             'Purchase price': inr(amount(p['unit_price'])), 'Supplier': p['supplier_name'] or 'Unassigned'}
            for p in products]


def order_lines(order):
    return [{'SKU': l['item_code'], 'Product': l['item_name'], 'Unit': l['unit'],
             'Quantity': quantity(l['qty']), 'Price': inr(amount(l['price'])),
             'Line total': inr(amount(line_value(l['qty'], l['price']))),
             'Received': quantity(l['received']), 'Outstanding': quantity(l['qty'] - l['received'])}
            for l in order['lines']]


extra_pages = {'Locations and reservations':'locations.py', 'Tracking and units':'tracking.py',
               'Customer orders':'customer_orders.py', 'Work orders':'work_orders.py', 'Material planning':'material_planning.py',
               'Quality checks':'quality.py', 'Outside work tracking':'jobwork.py', 'Cost analysis':'production_costs.py',
               'Assembly and jobs':'manufacturing.py', 'Quotations and bills':'purchasing.py',
               'Sales and invoices':'sales.py', 'Documents':'documents.py', 'Returnables and repairs':'returns.py',
               'Reports':'reports.py', 'Exceptions':'exceptions.py', 'Offline entry':'offline.py', 'Settings':'settings.py'}
pages = ['Overview', 'Products', 'Stock movements', 'Locations and reservations', 'Tracking and units',
         'Customer orders', 'Work orders', 'Material planning', 'Quality checks', 'Outside work tracking', 'Cost analysis',
         'Assembly and jobs', 'Quotations and bills', 'Purchase orders', 'Sales and invoices',
         'Suppliers', 'Returnables and repairs', 'Reports', 'Exceptions', 'Documents',
         'Offline entry', 'Import and backup', 'Settings']
translations = {'Overview':'अवलोकन', 'Products':'उत्पाद', 'Suppliers':'आपूर्तिकर्ता', 'Stock movements':'स्टॉक लेनदेन',
    'Customer orders':'ग्राहक आदेश', 'Work orders':'उत्पादन आदेश', 'Material planning':'सामग्री योजना',
    'Quality checks':'गुणवत्ता जांच', 'Outside work tracking':'बाहरी काम ट्रैकिंग', 'Cost analysis':'लागत विश्लेषण',
    'Purchase orders':'खरीद आदेश', 'Import and backup':'आयात और बैकअप', 'Assembly and jobs':'असेंबली और जॉब',
    'Locations and reservations':'स्थान और आरक्षण', 'Tracking and units':'बैच और इकाइयाँ', 'Sales and invoices':'बिक्री और बिल',
    'Quotations and bills':'कोटेशन और खरीद बिल', 'Documents':'दस्तावेज़', 'Returnables and repairs':'वापसी और मरम्मत',
    'Reports':'रिपोर्ट', 'Exceptions':'ध्यान देने योग्य', 'Offline entry':'ऑफ़लाइन प्रविष्टि', 'Settings':'सेटिंग्स'}

def sign_out():
    # Callbacks run before rendering so the previous role's widgets cannot survive a logout rerun.
    store.logout()
    st.session_state.clear()

with sidebar_content.container():
    sidebar_brand(business.get('business_name', config.BUSINESS_NAME), bool(demo_accounts))
    language = st.session_state.get('nav_language', business.get('language', 'English'))
    st.html('<div class="nav-heading">WORKSPACE</div>')
    with st.container(key='workspace_navigation'):
        page = st.radio('Workspace', pages, key='page', label_visibility='collapsed',
                        format_func=lambda p: f':material/{PAGE_ICONS[p]}: ' + (translations.get(p,p) if language=='Hindi' else p))
    with st.container(key='sidebar_account'):
        st.selectbox('Navigation language / भाषा', ['English','Hindi'],
                     index=int(business.get('language')=='Hindi'), key='nav_language')
        st.caption(f'{actor} · {identity["role"]}')
        st.button('Sign out', on_click=sign_out, width='stretch', icon=':material/logout:')

def navigate_to(target):
    st.session_state['page'] = target

if 'notice' in st.session_state:
    st.success(st.session_state.pop('notice'))

products = store.products()
suppliers = store.suppliers()
product_lookup = {p['id']: p for p in products}
supplier_lookup = {s['id']: s for s in suppliers}
product_label = lambda pid: f'{product_lookup[pid]["item_name"]} · {product_lookup[pid]["item_code"]}'
supplier_label = lambda sid: f'{supplier_lookup[sid]["name"]} · {supplier_lookup[sid]["email"] or "no email"}'
locations = store.locations()
location_lookup = {l['id']: l for l in locations if l['kind']!='jobwork'}
location_label = lambda lid: location_lookup[lid]['name']

def pick_product(label='Product', key=None):
    if not product_lookup:
        st.info('Add or import products first.')
        st.stop()
    return st.selectbox(label, list(product_lookup), format_func=product_label, key=key)

def pick_location(label='Location', key=None):
    return st.selectbox(label, list(location_lookup), format_func=location_label, key=key)

def pick_batch(pid, lid=None, label='Batch / serial', key=None, auto=False):
    if product_lookup[pid]['tracking']=='none':
        return None
    batches = store.batches(pid,lid)
    lookup = {b['id']:b for b in batches}
    options = [None]+list(lookup)
    return st.selectbox(label, options, format_func=lambda b: ('Automatic earliest expiry' if auto else 'Choose batch / serial') if b is None else f'{lookup[b]["code"]} · {quantity(lookup[b]["stock"])} on hand', key=key)

page_content = st.empty()
with page_content.container(key='workspace_content'):
    workspace_bar(business.get('business_name', config.BUSINESS_NAME), page, bool(demo_accounts))
    if page in extra_pages:
        runpy.run_path(str(Path(__file__).parent/'app_pages'/extra_pages[page]), init_globals={
            'st':st,'store':store,'actor':actor,'business':business,'identity':identity,'act':act,'grid':grid,'operation_key':operation_key,
            'products':products,'product_lookup':product_lookup,'product_label':product_label,'suppliers':suppliers,'supplier_lookup':supplier_lookup,
            'supplier_label':supplier_label,'locations':locations,'location_lookup':location_lookup,'location_label':location_label,
            'pick_product':pick_product,'pick_location':pick_location,'pick_batch':pick_batch,
            'amount':amount,'quantity':quantity,'inr':inr,'csv_bytes':csv_bytes,'ValidationError':ValidationError})
    elif page == 'Overview':
        st.title('Inventory overview')
        st.caption('Stock on hand, replenishment and orders awaiting delivery.')
        orders = store.orders()
        recommendations = store.recommendations()
        with st.container(key='overview_metrics'):
            metrics = st.columns(4)
            metrics[0].metric('Products', len(products))
            metrics[1].metric('Need replenishment', len(recommendations))
            metrics[2].metric('Open orders', sum(o['state'] not in ('received', 'cancelled') for o in orders))
            metrics[3].metric('Stock at purchase prices', inr(amount(sum(line_value(p['stock'], p['unit_price']) for p in products))))
        with st.container(key='overview_actions', horizontal=True):
            st.button('Add product', icon=':material/add:', on_click=navigate_to, args=('Products',), disabled=not store.allowed('catalogue'))
            st.button('Record stock movement', icon=':material/swap_horiz:', on_click=navigate_to, args=('Stock movements',), disabled=not store.allowed('inventory'))
            st.button('View purchase orders', icon=':material/shopping_cart:', on_click=navigate_to, args=('Purchase orders',))
        if not products:
            st.info('Start by importing an inventory file or adding your first product. The supplied sample is available in Import and backup.')
        else:
            with st.container(key='overview_body'):
                main, aside = st.columns([2.4, 1], gap='large')
            with main:
                st.subheader('Replenishment suggestions')
                st.caption('Prioritize the materials that need ordering.')
                if not recommendations:
                    st.success('Current stock and open orders cover all reorder levels.')
                else:
                    grid([{'Product': p['item_name'], 'Order quantity': quantity(p['suggested_qty']), 'Unit': p['unit'],
                           'Available': quantity(p['available']), 'Supplier': p['supplier_name'] or 'Assign a supplier',
                           'SKU': p['item_code'], 'Target': quantity(p['effective_reorder_level']),
                           'On order': quantity(p['incoming']), 'In drafts': quantity(p['planned'])} for p in recommendations])
                    supplier_ids = sorted({p['supplier_id'] for p in recommendations if p['supplier_id']})
                    if supplier_ids:
                        chosen = st.selectbox('Prepare an order for', supplier_ids, format_func=supplier_label)
                        if st.button('Create reorder draft', type='primary', icon=':material/add_shopping_cart:'):
                            act('reorder', lambda: store.create_po(chosen, [], actor=actor, token=operation_key('reorder'), reorder=True),
                                'Draft created. Review and approve it in Purchase orders.')
                    if any(not p['supplier_id'] for p in recommendations):
                        st.info('Assign a supplier on the Products page for items without one.')
                with st.expander('How these suggestions are calculated'):
                    st.caption('Suggestions use internal stock after reservations, open orders, recent usage, supplier lead time and purchase pack rules. Owned stock held outside the business stays visible in location reports.')
            with aside:
                with st.container(key='attention_panel'):
                    st.subheader('Needs attention')
                    st.caption('Unreviewed exceptions in your workspace.')
                    attention_summary(store.alerts())
                    st.button('Review exceptions', icon=':material/arrow_forward:', on_click=navigate_to,
                              args=('Exceptions',), width='stretch')
            st.subheader('Current stock')
            grid(stock_rows(products))
        st.caption('Stock value uses current product purchase prices; it is not FIFO or weighted-average accounting valuation.')

    elif page == 'Products':
        st.title('Products')
        search = st.text_input('Search products', placeholder='Name, SKU, category or barcode')
        filtered = [p for p in products if search.casefold() in ' '.join(str(p.get(k) or '') for k in ('item_name','item_code','category','barcode')).casefold()]
        if filtered:
            grid(stock_rows(filtered))
        elif products:
            st.info('No products match your search.')
        else:
            st.info('Add a product below or import your inventory.')
        st.subheader('Add or edit a product')
        selected = st.selectbox('Product record', [None] + list(product_lookup), format_func=lambda x: 'Add new product' if x is None else product_label(x))
        current = product_lookup.get(selected, {})
        form_key = f'product_{selected}_{current.get("version", 0)}'
        with st.form(form_key):
            left, right = st.columns(2)
            code = left.text_input('SKU', value=current.get('item_code', ''))
            name = right.text_input('Product name', value=current.get('item_name', ''))
            category = left.text_input('Category', value=current.get('category', ''))
            barcode = right.text_input('Barcode', value=current.get('barcode') or '')
            unit = left.text_input('Stock unit', value=current.get('unit', 'Pcs'), disabled=selected is not None,
                                   help='Quantities use this unit. Use a new SKU for a different unit.')
            supplier_options = [None] + list(supplier_lookup)
            supplier_id = right.selectbox('Default supplier', supplier_options,
                                         index=supplier_options.index(current.get('supplier_id')),
                                         format_func=lambda x: 'Unassigned' if x is None else supplier_label(x))
            price = left.text_input('Purchase price (₹)', value=amount(current.get('unit_price', 0)))
            selling = right.text_input('Selling price (₹)', value=amount(current.get('selling_price', 0)))
            threshold = left.text_input('Reorder level', value=quantity(current.get('reorder_level', 0)))
            reorder = right.text_input('Fixed reorder quantity', value=quantity(current.get('reorder_qty', 0)),
                                       help='Zero uses a target of 1.5 times the reorder level.')
            opening = st.text_input('Opening stock', value='0') if selected is None else '0'
            if selected is not None:
                st.caption('Use Stock movements to record a receipt, issue or physical count. Product editing does not change stock.')
            save = st.form_submit_button('Save product', type='primary')
        if save:
            raw = dict(item_code=code, item_name=name, unit=unit, category=category, barcode=barcode,
                       unit_price=price, selling_price=selling, reorder_level=threshold, reorder_qty=reorder)
            act(form_key, lambda: store.save_product(raw, actor=actor, token=operation_key(form_key), product_id=selected,
                                                    version=current.get('version'), opening=opening, supplier_id=supplier_id), 'Product saved.')

    elif page == 'Suppliers':
        st.title('Suppliers')
        if suppliers:
            grid([{'Supplier': s['name'], 'Email': s['email'], 'Phone': s['phone'],
                   'Lead time (days)': s['lead_days'], 'Payment terms': s['terms']} for s in suppliers])
        selected = st.selectbox('Supplier record', [None] + list(supplier_lookup), format_func=lambda x: 'Add new supplier' if x is None else supplier_label(x))
        current = supplier_lookup.get(selected, {})
        with st.form(f'supplier_{selected}_{current.get("version",0)}'):
            left, right = st.columns(2)
            name = left.text_input('Supplier name', value=current.get('name', ''))
            address = right.text_input('Email address', value=current.get('email', ''))
            phone = left.text_input('Phone', value=current.get('phone', ''))
            lead_days = right.number_input('Lead time in days', min_value=0, max_value=3650, value=current.get('lead_days', 0))
            terms = st.text_input('Payment terms', value=current.get('terms', ''))
            st.caption('An email is optional for suppliers contacted by phone. Existing orders retain the supplier details reviewed when created.')
            save = st.form_submit_button('Save supplier', type='primary')
        if save:
            act('supplier', lambda: store.save_supplier(name, address, phone, terms, lead_days, actor=actor,
                                                       supplier_id=selected, version=current.get('version')), 'Supplier saved.')

    elif page == 'Stock movements':
        st.title('Stock movements')
        st.caption('Record what physically arrived, left or changed. Receive purchase orders on the Purchase orders page.')
        if products:
            selected = st.selectbox('Product', list(product_lookup), format_func=product_label)
            product = product_lookup[selected]
            lid = pick_location(key='movement_location')
            bid = pick_batch(selected,lid,key='movement_batch',auto=True)
            local = next((r['qty'] for r in store.location_stock(lid) if r['product_id']==selected),0)
            if bid is not None:
                local = next(b['stock'] for b in store.batches(selected,lid) if b['id']==bid)
            st.metric('On hand at location', f'{quantity(local)} {product["unit"]}')
            kinds = {'receipt': 'Receipt without a purchase order', 'sale': 'Sale / customer delivery',
                     'issue': 'Internal use', 'customer_return': 'Customer return', 'supplier_return': 'Return to supplier',
                     'damage': 'Damage / waste', 'adjustment': 'Signed correction', 'stock_count': 'Physical stock count'}
            kind = st.selectbox('Movement type', list(kinds), format_func=kinds.get)
            count_baseline = None
            if kind == 'stock_count':
                baseline_key = f'count_baseline_{selected}_{lid}_{bid}'
                count_baseline = st.session_state.setdefault(baseline_key, local)
                st.caption(f'Count started with {quantity(count_baseline)} {product["unit"]} recorded in stock.')
                if local != count_baseline:
                    st.warning('Stock changed after you started counting. Check the physical stock again and restart the count.')
                if st.button('Restart stock count'):
                    st.session_state[baseline_key] = local
                    page_content.empty()
                    st.rerun()
            with st.form(f'move_{selected}_{kind}', clear_on_submit=True):
                value = st.text_input('Counted stock' if kind == 'stock_count' else 'Quantity', value='',
                                      help='Up to three decimal places. A signed correction can be positive or negative.')
                reason = st.text_input('Reason')
                reference = st.text_input('Reference', help='Invoice, delivery note or customer reference, if available.')
                conversions = [product['unit']] + [c['unit'] for c in store.conversions(selected)]
                entry_unit = st.selectbox('Entry unit', conversions, disabled=kind=='stock_count')
                unit_cost = st.text_input('Receipt cost per base unit (₹)', value=amount(product['unit_price'])) if kind in ('receipt','customer_return') else None
                if kind == 'stock_count':
                    st.caption('Enter the total physically counted. The difference will be recorded as a correction.')
                save = st.form_submit_button('Record movement', type='primary')
            if save:
                scope = f'move_{selected}_{kind}'
                act(scope, lambda: store.move_stock(selected, kind, value, reason, actor=actor, token=operation_key(scope),
                                                    reference=reference, expected_stock=count_baseline,location_id=lid,batch_id=bid,
                                                    unit=entry_unit,unit_cost=unit_cost), 'Stock movement recorded.')
        else:
            st.info('Add or import a product first.')
        st.subheader('Movement history')
        history_product = st.selectbox('History for', [None] + list(product_lookup), format_func=lambda x: 'All products' if x is None else product_label(x))
        history = store.movements(history_product)
        if history:
            rows = [{'Date (UTC)': m['created_at'], 'SKU': m['item_code'], 'Product': m['item_name'],
                     'Change': quantity(m['delta']), 'Unit': m['unit'], 'Type': m['kind'].replace('_', ' '),
                     'Reason': m['reason'], 'Reference': m['reference'], 'Operator': m['actor']} for m in history]
            grid(rows)
            st.download_button('Export movement history', csv_bytes(rows), 'stock_movements.csv', 'text/csv')
        else:
            st.info('No movements have been recorded.')

    elif page == 'Purchase orders':
        st.title('Purchase orders')
        st.caption('Create, review, approve, place and receive orders. All amounts are in INR.')
        if suppliers and products:
            with st.expander('Create a purchase order'):
                sid = st.selectbox('Order supplier', list(supplier_lookup), format_func=supplier_label, key='new_order_supplier')
                selected_products = st.multiselect('Order products', list(product_lookup), format_func=product_label)
                if selected_products:
                    scope = f'new_po_{sid}_{"_".join(map(str, selected_products))}'
                    with st.form(scope):
                        lines = []
                        for pid in selected_products:
                            p = product_lookup[pid]
                            st.write(f'**{p["item_name"]} · {p["item_code"]}** ({p["unit"]})')
                            left, right = st.columns(2)
                            qty = left.text_input('Order quantity', value='1', key=f'{scope}_{pid}_qty')
                            price = right.text_input('Unit price (₹)', value=amount(p['unit_price']), key=f'{scope}_{pid}_price')
                            lines.append({'product_id': pid, 'qty': qty, 'price': price})
                        notes = st.text_area('Order notes', key=f'{scope}_notes')
                        create = st.form_submit_button('Save draft', type='primary')
                    if create:
                        act(scope, lambda: store.create_po(sid, lines, notes=notes, actor=actor, token=operation_key(scope)), 'Purchase order draft saved.')
        else:
            st.info('Add at least one product and supplier to create an order.')
        orders = store.orders()
        if orders:
            grid([{'Order': o['number'], 'Supplier': o['supplier_name'], 'Status': o['state'].replace('_', ' '),
                   'Created (UTC)': o['created_at'], 'Revision': o['revision']} for o in orders])
            lookup = {o['id']: o for o in orders}
            oid = st.selectbox('Open an order', list(lookup), format_func=lambda i: f'{lookup[i]["number"]} · {lookup[i]["supplier_name"]}')
            order = store.order(oid)
            key = f'po_{oid}_v{order["revision"]}'
            st.subheader(order['number'])
            st.write(f'**{order["supplier_name"]}** · {order["supplier_email"] or "No email address"}')
            st.caption(f'Status: {order["state"].replace("_", " ")} · Revision {order["revision"]}')
            with st.expander('Expected delivery date'):
                with st.form(key+'_due'):
                    due = st.date_input('Delivery due', value=date.fromisoformat(order['due_date']) if order['due_date'] else date.today())
                    due_save = st.form_submit_button('Save delivery date',disabled=not store.allowed('purchase'))
                if due_save:
                    act(key+'_due',lambda:store.set_order_due(oid,due.isoformat(),actor=actor),'Expected delivery saved.')
            grid(order_lines(order))
            st.metric('Order total', inr(amount(order['total'])))
            st.caption('Excludes tax and freight. Orders use saved line prices; changing a product price does not change an existing order.')
            subject, body = (order['subject'], order['body']) if order['approval_hash'] else store.draft_email(order)
            with st.expander('Email and order document', expanded=order['state'] == 'draft'):
                st.text_input('Subject', value=subject, disabled=True, key=key+'_subject')
                st.text_area('Purchase order text', value=body, height=290, disabled=True, key=key+'_body')
                st.download_button('Download order', body.encode('utf-8'), order['number']+'.txt', 'text/plain', key=key+'_download')
            if order['state'] in ('draft', 'approved'):
                with st.expander('Edit quantities, prices and notes'):
                    with st.form(key+'_edit'):
                        edits = []
                        for line in order['lines']:
                            st.write(f'**{line["item_name"]}** ({line["unit"]})')
                            left, right = st.columns(2)
                            qty = left.text_input('Quantity', value=quantity(line['qty']), key=f'{key}_{line["id"]}_qty')
                            price = right.text_input('Price (₹)', value=amount(line['price']), key=f'{key}_{line["id"]}_price')
                            edits.append({'product_id': line['product_id'], 'qty': qty, 'price': price})
                        notes = st.text_area('Notes', value=order['notes'], key=key+'_notes')
                        st.caption('Saving creates a new draft revision and clears any earlier approval.')
                        save = st.form_submit_button('Save order revision')
                    if save:
                        act(key, lambda: store.revise_po(oid, edits, notes, actor=actor, revision=order['revision']), 'Order updated. Review the new revision before approval.')
                if st.button('Run dry preview', key=key+'_dry'):
                    try:
                        store.send_po(oid, actor=actor, dry_run=True)
                        st.success('Preview complete. No email sent; this order is still available for approval or live sending.')
                    except ValidationError as exc:
                        st.error(str(exc))
            if order['state'] == 'draft':
                confirmed = st.checkbox('I reviewed the supplier, quantities, prices and order text.', key=key+'_reviewed')
                if st.button('Approve order', type='primary', disabled=not confirmed, key=key+'_approve'):
                    act(key, lambda: store.approve_po(oid, actor=actor, revision=order['revision']), 'Order approved. Place it by email or record your supplier confirmation.')
            if order['state'] == 'approved':
                live = st.checkbox('Send this approved order as a live email', key=key+'_live')
                if st.button('Send approved email', type='primary', disabled=not live, key=key+'_send'):
                    try:
                        result = store.send_po(oid, actor=actor, dry_run=False)
                        st.session_state['notice'] = 'Order emailed and recorded.' if result['status'] == 'ok' else 'Email attempt recorded. Review the delivery status below.'
                        page_content.empty()
                        st.rerun()
                    except (ValidationError, sqlite3.OperationalError) as exc:
                        st.error(str(exc))
                with st.form(key+'_manual'):
                    reference = st.text_input('Supplier confirmation or external order reference')
                    placed = st.form_submit_button('Record order placed outside email')
                if placed:
                    act(key, lambda: store.place_manually(oid, reference, actor=actor, revision=order['revision']), 'Order marked as placed. Receive the goods when they arrive.')
            if order['last_error']:
                st.warning(order['last_error'])
            if order['state'] in ('sending', 'delivery_unknown'):
                st.warning('Delivery is not confirmed. Check the sent mailbox and supplier before retrying. An active attempt can be reconciled after five minutes.')
                with st.form(key+'_reconcile'):
                    outcome = st.selectbox('Verified delivery outcome', ['Supplier received it', 'Confirmed not delivered'])
                    evidence = st.text_input('Evidence or supplier confirmation')
                    verified = st.checkbox('I checked the delivery outcome.')
                    reconcile = st.form_submit_button('Save verified outcome')
                if reconcile and verified:
                    act(key, lambda: store.reconcile_delivery(oid, outcome == 'Supplier received it', evidence, actor=actor), 'Delivery status reconciled.')
                elif reconcile:
                    st.error('Confirm that the delivery outcome has been checked.')
            if order['state'] in ('sent', 'partial'):
                st.subheader('Receive goods')
                receipt_location = pick_location('Receiving location',key=key+'_location')
                with st.form(key+'_receive', clear_on_submit=True):
                    received = {}
                    receipt_batches = {}
                    for line in order['lines']:
                        if line['qty'] > line['received']:
                            received[line['id']] = st.text_input(f'{line["item_name"]}: received now ({line["unit"]})', value='0', key=f'{key}_receive_{line["id"]}_{line["received"]}')
                            receipt_batches[line['id']] = pick_batch(line['product_id'],receipt_location,key=f'{key}_batch_{line["id"]}')
                    reference = st.text_input('Delivery reference')
                    freight = st.text_input('Freight / handling for this receipt (₹)',value='0',help='Allocated by goods value and included in stock cost. Exclude recoverable tax.')
                    quality_hold = st.checkbox('Quarantine this receipt until incoming quality inspection passes')
                    receive = st.form_submit_button('Record goods received', type='primary')
                if receive:
                    act(key+'_receive', lambda: store.receive_po(oid, received, actor=actor, token=operation_key(key+'_receive'), reference=reference,
                        location_id=receipt_location,batches={k:v for k,v in receipt_batches.items() if v is not None},freight=freight,quality_hold=quality_hold), 'Goods received and stock updated. Inspect quarantined receipts on Quality checks.')
            if order['state'] in ('draft', 'approved', 'sent', 'partial'):
                with st.expander('Cancel remaining order'):
                    with st.form(key+'_cancel'):
                        reason = st.text_input('Cancellation reason')
                        confirmed = st.checkbox('I have arranged cancellation with the supplier if the order was already placed.')
                        cancel = st.form_submit_button('Cancel order')
                    if cancel and confirmed:
                        act(key, lambda: store.cancel_po(oid, reason, actor=actor), 'Remaining order cancelled. Previously received stock is unchanged.')
                    elif cancel:
                        st.error('Confirm the cancellation before continuing.')
        else:
            st.info('No purchase orders yet. Create a draft here or use the replenishment suggestions on Overview.')

    elif page == 'Import and backup':
        st.title('Import and backup')
        st.subheader('Import new products')
        st.caption('Preview the file before saving. Imports add products and opening balances; existing SKUs are rejected so an old spreadsheet cannot overwrite live stock.')
        upload = st.file_uploader('Inventory file', type=['xlsx', 'csv'])
        use_sample = st.checkbox('Preview the supplied sample inventory', value=False, disabled=upload is not None)
        source_bytes = upload.getvalue() if upload else (config.INVENTORY_PATH.read_bytes() if use_sample and config.INVENTORY_PATH.exists() else None)
        filename = upload.name if upload else str(config.INVENTORY_PATH)
        if source_bytes is not None:
            fingerprint = hashlib.sha256(source_bytes).hexdigest()
            try:
                frame = load_table(io.BytesIO(source_bytes), filename)
                with st.expander('Map spreadsheet columns', expanded=True):
                    mapping = {}
                    options = ['Ignore'] + list(FIELDS)
                    for col in frame.columns:
                        inferred = normalize_header(col)
                        choice = st.selectbox(str(col), options, index=options.index(inferred) if inferred in options else 0,
                                              key=f'map_{fingerprint}_{col}')
                        mapping[str(col)] = choice
                records, errors = validate_table(frame, mapping)
                existing = {p['item_code'].casefold() for p in products}
                for row in records:
                    if row['item_code'].casefold() in existing:
                        errors.append(f'SKU {row["item_code"]} already exists. Edit it in Products; use a stock count to correct stock.')
                if records:
                    grid(records)
                if errors:
                    if store.allowed('catalogue'):
                        store.record_import_issue(fingerprint, '\n'.join(errors)[:4000],actor=actor)
                    st.error('Import blocked. Fix these issues before saving:')
                    for error in errors[:40]:
                        st.write('• ' + error)
                    if len(errors) > 40:
                        st.caption(f'{len(errors)-40} more errors. Correct the file and preview again.')
                else:
                    st.success(f'{len(records)} new products are ready to import.')
                confirm = st.checkbox('I reviewed the products and opening balances.', key='confirm_'+fingerprint)
                if st.button('Import products', type='primary', disabled=bool(errors) or not confirm):
                    act('import_'+fingerprint, lambda: store.import_products(records, actor=actor, token=operation_key('import_'+fingerprint)),
                        lambda count: f'Imported {count} products. Opening balances are recorded in stock history.')
            except Exception as exc:
                st.error(f'Unable to preview this file: {exc}')
        template = [{'item_code':'SKU-001', 'item_name':'Example product', 'current_stock':'0', 'reorder_level':'10',
                     'reorder_qty':'20', 'unit':'Pcs', 'unit_price':'12.50', 'selling_price':'15.00',
                     'supplier_name':'Example supplier', 'supplier_email':'orders@example.com', 'category':'General', 'barcode':''}]
        st.download_button('Download CSV import template', csv_bytes(template), 'inventory_template.csv', 'text/csv')
        st.subheader('Export and backup')
        export = [{'item_code': p['item_code'], 'item_name': p['item_name'], 'current_stock': quantity(p['stock']),
                   'reorder_level': quantity(p['reorder_level']), 'reorder_qty': quantity(p['reorder_qty']),
                   'unit': p['unit'], 'unit_price': amount(p['unit_price']), 'selling_price': amount(p['selling_price']),
                   'supplier_name': p['supplier_name'] or '', 'supplier_email': p['supplier_email'] or '',
                   'category': p['category'], 'barcode': p['barcode'] or ''} for p in products]
        st.download_button('Export current inventory', csv_bytes(export, list(FIELDS)), 'current_inventory.csv', 'text/csv')
        if st.button('Prepare full backup', disabled=not store.allowed('backup')):
            st.session_state['backup_bytes'] = store.backup()
            st.session_state['backup_date'] = date.today().isoformat()
        if 'backup_bytes' in st.session_state:
            st.download_button('Download prepared backup', st.session_state['backup_bytes'],
                               f'stocklist-{st.session_state["backup_date"]}.sqlite3', 'application/octet-stream')
            st.caption('This is a snapshot taken when you clicked Prepare full backup. Prepare again after more changes.')
        st.caption('A full backup includes stock movements, orders and audit history. See README for offline restore instructions.')
        with st.expander('Activity history'):
            audit = store.audit()
            if audit:
                grid([{'Date (UTC)': a['created_at'], 'Operator': a['actor'], 'Action': a['action'].replace('_', ' '),
                       'Record': a['entity'], 'Details': a['detail']} for a in audit])
                st.download_button('Export activity history', csv_bytes(audit), 'activity_history.csv', 'text/csv')
            else:
                st.info('No activity yet.')

    workspace_footer()
