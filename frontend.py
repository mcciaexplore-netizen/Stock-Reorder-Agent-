"""Presentation helpers for the MCCIA-branded Stocklist workspace."""
import base64
from collections import Counter
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / 'static' / 'branding' / 'logo-mccia-white-blue-new.png'
PAGE_ICONS = {
    'Customer orders': 'assignment', 'Work orders': 'factory', 'Material planning': 'account_tree',
    'Quality checks': 'verified', 'Outside work tracking': 'local_shipping', 'Cost analysis': 'calculate',
    'Overview': 'space_dashboard', 'Products': 'inventory_2', 'Suppliers': 'handshake',
    'Stock movements': 'swap_horiz', 'Purchase orders': 'shopping_cart', 'Import and backup': 'cloud_upload',
    'Locations and reservations': 'warehouse', 'Tracking and units': 'qr_code_2',
    'Assembly and jobs': 'precision_manufacturing', 'Quotations and bills': 'request_quote',
    'Sales and invoices': 'receipt_long', 'Documents': 'folder_open', 'Returnables and repairs': 'build',
    'Reports': 'bar_chart', 'Exceptions': 'notifications', 'Offline entry': 'offline_bolt', 'Settings': 'settings',
}


def apply_brand():
    st.html(ROOT / 'assets' / 'brand.css')


def access_form(*, setup=False, demos=()):
    """Native form values are returned to the existing authentication flow."""
    result = dict(submitted=False, demo=None, username='', password='', name='', confirm='')
    with st.container(key='auth_shell'):
        left, right = st.columns([1.05, 1], gap='large')
        with left:
            logo = base64.b64encode(LOGO.read_bytes()).decode('ascii')
            st.html(f'''<section class="brand-hero" aria-label="About Stocklist">
                <div class="brand-lockup"><img class="brand-logo" src="data:image/png;base64,{logo}" alt="MCCIA logo" /><span class="product-name">STOCKLIST</span></div>
                <p class="eyebrow">Inventory &amp; operations for every growing business</p>
                <h2>Know your stock.<br /><span>Keep work moving.</span></h2>
                <p class="hero-copy">One workspace for stock, purchasing, orders, billing and day-to-day operations.</p>
                <div class="flow-diagram" aria-label="Stocklist supports stock, orders and accounts">
                    <div class="flow-step"><span class="flow-number">01</span><div><strong>Stock in view</strong><small>Products, locations and availability</small></div></div>
                    <div class="flow-step"><span class="flow-number">02</span><div><strong>Orders moving</strong><small>Purchasing, customers and commitments</small></div></div>
                    <div class="flow-step"><span class="flow-number">03</span><div><strong>Accounts connected</strong><small>Invoices, returns and payments</small></div></div>
                </div><p class="hero-foot">TRADING &nbsp; / &nbsp; SERVICES &nbsp; / &nbsp; ASSEMBLY &nbsp; / &nbsp; MANUFACTURING</p>
                </section>''')
        with right:
            with st.container(key='signin_panel'):
                st.title('Set up Stocklist' if setup else 'Sign in to Stocklist')
                st.caption('Create your owner account to get started.' if setup else 'Welcome back. Open your business workspace.')
                result['feedback'] = st.empty()
                with st.form('setup_owner' if setup else 'login', border=False):
                    result['username'] = st.text_input('Owner username' if setup else 'Username', placeholder='Your username')
                    if setup:
                        result['name'] = st.text_input('Your name')
                    result['password'] = st.text_input('Password (at least 12 characters)' if setup else 'Password', type='password')
                    if setup:
                        result['confirm'] = st.text_input('Confirm password', type='password')
                    result['submitted'] = st.form_submit_button('Create owner account' if setup else 'Sign in',
                        type='primary', width='stretch', icon=':material/arrow_forward:', icon_position='right')
                if demos:
                    with st.container(key='demo_access'):
                        st.subheader('Explore a sample business')
                        st.caption('Choose a role. No password needed for the demo.')
                        columns = st.columns(2)
                        icons = {'owner': 'dashboard', 'warehouse': 'warehouse', 'accountant': 'receipt_long', 'viewer': 'visibility'}
                        for index, profile in enumerate(demos):
                            with columns[index % 2]:
                                if st.button(profile['label'], key='demo_login_' + profile['role'],
                                             width='stretch', icon=f':material/{icons[profile["role"]]}:'):
                                    result['demo'] = profile
                                st.caption(profile['description'])
                        st.caption('Sample records · shared demo workspace · email sending off')
            st.html('<div class="auth-foot">Stocklist &nbsp;·&nbsp; Your inventory, connected.</div>')
    return result


def sidebar_brand(business_name, demo):
    st.logo(str(LOGO), size='large', link='https://mcciapune.com/')
    st.html(f'<div class="sidebar-brand"><strong>Stocklist</strong><p>{escape(business_name)}</p></div>')
    if demo:
        st.html('<span class="workspace-tag">Demo workspace</span>')


def workspace_bar(business_name, page, demo):
    tag = '<span class="workspace-tag">Demo workspace</span>' if demo else ''
    st.html(f'<div class="workspace-bar"><div class="crumb">{escape(business_name)} &nbsp;/&nbsp; <strong>{escape(page)}</strong></div>'
            f'<div class="meta">{tag}<span>{date.today():%d %b %Y}</span></div></div>')


def attention_summary(alerts):
    counts = Counter(a['category'] for a in alerts if not a['acknowledged'])
    priority = ['Delivery overdue', 'Payment overdue', 'Job budget', 'Supplier bill', 'Batch expiry', 'Returnable overdue', 'Low stock']
    items = sorted(counts.items(), key=lambda item: (priority.index(item[0]) if item[0] in priority else len(priority), item[0]))[:4]
    if items:
        st.html('<div class="attention-list">' + ''.join(
            f'<div class="attention-row"><span class="attention-number">{count}</span><span class="attention-label">{escape(category)}</span></div>'
            for category, count in items) + '</div>')
    else:
        st.html('<p class="attention-empty">No new exceptions to review.</p>')


def workspace_footer():
    st.html('<footer class="stock-footer"><span>Stocklist · Inventory &amp; operations</span><span>Trading / Services / Assembly / Manufacturing</span></footer>')
