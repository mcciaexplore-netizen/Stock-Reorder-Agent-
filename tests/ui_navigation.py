"""Navigate real UI controls through the seven core sections."""

PARENTS = {
    'Exceptions': 'Overview', 'Tracking and units': 'Products',
    'Locations and reservations': 'Stock movements', 'Suppliers': 'Purchase orders',
    'Quotations and bills': 'Purchase orders', 'Quality checks': 'Purchase orders',
    'Customer orders': 'Sales and invoices', 'Import and backup': 'Settings',
}


def open_page(app, target):
    if 'detail_page' in app.session_state and app.session_state['detail_page']:
        app.button(key='back_to_section').click().run()
    app.radio(key='page').set_value(PARENTS.get(target, target)).run()
    if target in PARENTS:
        app.button(key='open_' + target).click().run()
    return app
