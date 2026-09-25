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
    result = dict(submitted=False, demo=None, username='', password='', name='', confirm='', is_register=False)
    if 'auth_mode' not in st.session_state:
        st.session_state['auth_mode'] = 'setup' if setup else 'login'
    
    current_mode = st.session_state['auth_mode']
    is_signup = (current_mode == 'setup')

    with st.container(key='auth_shell'):
        left, right = st.columns([1.08, 1], gap='large')
        with left:
            logo = base64.b64encode(LOGO.read_bytes()).decode('ascii')
            st.html(f'''<section class="brand-hero" aria-label="About Stocklist">
                <div class="brand-lockup">
                    <img class="brand-logo" src="data:image/png;base64,{logo}" alt="MCCIA logo" />
                    <span class="product-badge"><span class="badge-dot"></span>STOCKLIST ENTERPRISE</span>
                </div>
                <div class="eyebrow-pill">Smart Inventory &amp; Operations Suite</div>
                <h2>Know your stock.<br /><span class="hero-gradient-text">Keep work moving.</span></h2>
                <p class="hero-copy">Unified workspace for real-time inventory control, supplier purchasing, order fulfillment, and multi-location operations.</p>
                <div class="flow-diagram" aria-label="Stocklist supports stock, orders and accounts">
                    <div class="flow-step">
                        <span class="flow-number">01</span>
                        <div class="flow-body">
                            <strong>Live Stock &amp; Valuation</strong>
                            <small>Real-time SKU visibility, locations &amp; reorder points</small>
                        </div>
                    </div>
                    <div class="flow-step">
                        <span class="flow-number">02</span>
                        <div class="flow-body">
                            <strong>Seamless Purchasing &amp; POs</strong>
                            <small>Supplier tracking, lead times &amp; goods receiving</small>
                        </div>
                    </div>
                    <div class="flow-step">
                        <span class="flow-number">03</span>
                        <div class="flow-body">
                            <strong>Connected Sales &amp; Billing</strong>
                            <small>Order commitments, delivery notes &amp; GST invoices</small>
                        </div>
                    </div>
                </div>
                <div class="hero-pills">
                    <span class="industry-chip">Trading</span>
                    <span class="industry-chip">Services</span>
                    <span class="industry-chip">Assembly</span>
                    <span class="industry-chip">Manufacturing</span>
                </div>
            </section>''')
        with right:
            with st.container(key='signin_panel'):
                st.title('Create your Account' if is_signup else 'Sign in to Stocklist')
                st.caption('Enter your details to create a new workspace account.' if is_signup else 'Welcome back. Open your business workspace.')
                result['feedback'] = st.empty()
                result['is_register'] = is_signup

                with st.form('auth_form', border=False):
                    result['username'] = st.text_input('Username', placeholder='Your username')
                    if is_signup:
                        result['name'] = st.text_input('Your full name', placeholder='e.g. Aarushi Gupta')
                    result['password'] = st.text_input('Password (at least 12 characters)' if is_signup else 'Password', type='password', placeholder='••••••••••••')
                    if is_signup:
                        result['confirm'] = st.text_input('Confirm password', type='password', placeholder='••••••••••••')
                    
                    submit_label = 'Create account' if is_signup else 'Sign in'
                    result['submitted'] = st.form_submit_button(submit_label,
                        type='primary', width='stretch', icon=':material/arrow_forward:', icon_position='right')
                
                # Switch between Sign In and Create Account
                if is_signup:
                    if st.button('Already have an account? Sign in', key='toggle_to_login', width='stretch', icon=':material/login:'):
                        st.session_state['auth_mode'] = 'login'
                        st.rerun()
                else:
                    if st.button('New user? Create an account', key='toggle_to_signup', width='stretch', icon=':material/person_add:'):
                        st.session_state['auth_mode'] = 'setup'
                        st.rerun()

                if demos and not is_signup:
                    with st.container(key='demo_access'):
                        st.html('''<div class="demo-divider">
                            <span>OR INSTANT EXPLORATION</span>
                        </div>''')
                        st.subheader('Try a Sample Business')
                        st.caption('Explore with preloaded data. Zero configuration needed.')
                        columns = st.columns(2)
                        icons = {'owner': 'dashboard', 'warehouse': 'warehouse', 'accountant': 'receipt_long', 'viewer': 'visibility'}
                        for index, profile in enumerate(demos):
                            with columns[index % 2]:
                                if st.button(profile['label'], key='demo_login_' + profile['role'],
                                             width='stretch', icon=f':material/{icons.get(profile["role"], "login")}:'):
                                    result['demo'] = profile
                                st.caption(profile['description'])
                        st.html('<div class="demo-note"><span class="badge-dot-amber"></span> Sandbox Mode · Instant session · Email sending disabled</div>')
            st.html('<div class="auth-foot">Powered by <strong>MCCIA</strong> &nbsp;·&nbsp; Stocklist Inventory Platform</div>')
    return result


def sidebar_brand(business_name, demo):
    st.logo(str(LOGO), size='large', link='https://mcciapune.com/')
    name_str = business_name or 'Stocklist Enterprise'
    st.html(f'''<div class="sidebar-brand-card">
        <div class="sidebar-brand-header">
            <strong>Stocklist</strong>
            <span class="badge-pill-mccia">MCCIA</span>
        </div>
        <p class="sidebar-business-name">{escape(str(name_str))}</p>
    </div>''')
    if demo:
        st.html('<div class="workspace-tag-container"><span class="workspace-tag">Interactive Sandbox</span></div>')


def workspace_bar(business_name, page, demo):
    name_str = business_name or 'Stocklist Enterprise'
    page_str = page or 'Overview'
    tag = '<span class="workspace-tag">Interactive Demo</span>' if demo else '<span class="workspace-tag-live">Live Workspace</span>'
    st.html(f'''<div class="workspace-bar">
        <div class="crumb">
            <span class="crumb-corp">{escape(str(name_str))}</span>
            <span class="crumb-sep">/</span>
            <strong class="crumb-page">{escape(str(page_str))}</strong>
        </div>
        <div class="meta">
            {tag}
            <span class="workspace-date"><i class="date-icon">📅</i> {date.today():%d %b %Y}</span>
        </div>
    </div>''')



def attention_summary(alerts):
    counts = Counter(a['category'] for a in alerts if not a['acknowledged'])
    priority = ['Delivery overdue', 'Payment overdue', 'Job budget', 'Supplier bill', 'Batch expiry', 'Returnable overdue', 'Low stock']
    items = sorted(counts.items(), key=lambda item: (priority.index(item[0]) if item[0] in priority else len(priority), item[0]))[:4]
    if items:
        st.html('<div class="attention-list">' + ''.join(
            f'''<div class="attention-row">
                <span class="attention-number">{count}</span>
                <div class="attention-info">
                    <span class="attention-label">{escape(category)}</span>
                    <span class="attention-hint">Action required</span>
                </div>
            </div>'''
            for category, count in items) + '</div>')
    else:
        st.html('''<div class="attention-empty-card">
            <span class="attention-check">✓</span>
            <div>
                <strong>All clear!</strong>
                <p>No critical exceptions or alerts pending review.</p>
            </div>
        </div>''')


def workspace_footer():
    st.html('''<footer class="stock-footer">
        <div class="footer-left">
            <strong>Stocklist</strong> · Intelligent Inventory &amp; Operations Management
        </div>
        <div class="footer-right">
            <span>Trading</span> · <span>Services</span> · <span>Assembly</span> · <span>Manufacturing</span>
        </div>
    </footer>''')
