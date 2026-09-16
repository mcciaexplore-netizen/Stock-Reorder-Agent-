"""Repeatable manufacturing examples, created through the normal business services."""
from datetime import date, timedelta
import json

from inventory import ValidationError, amount

SEED_KEY = '_demo_manufacturing_v1'
ACTOR = 'Demo setup'


def seed_sample_data(store):
    """Add the sample pack once, retaining existing products and subsequent demo edits."""
    identity = store.identity()
    if not identity or identity['role'] != 'owner':
        raise ValidationError('Sign in as an owner before loading demo data.')
    with store.connect(True) as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (SEED_KEY,)).fetchone()
        state = json.loads(row['value']) if row else {'date': date.today().isoformat(), 'complete': False}
        if state['complete']:
            return False
        db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (SEED_KEY, json.dumps(state)))
    anchor = date.fromisoformat(state['date'])
    day = lambda offset: (anchor + timedelta(days=offset)).isoformat()
    token = lambda name: 'demo-manufacturing-v1:' + name

    def find_or_create(rows, key, value, create):
        match = next((r for r in rows if r[key] == value), None)
        return match['id'] if match else create()

    settings = store.settings()
    defaults = {'business_name': 'Demo manufacturing company',
                'business_address': 'Sample industrial estate, Pune, Maharashtra',
                'default_industry': 'manufacturing'}
    missing = {k: v for k, v in defaults.items() if not settings.get(k)}
    if missing:
        store.save_settings(missing, actor=ACTOR)

    suppliers = {}
    for code, name, lead in [('metal', 'Demo Deccan Metals', 7),
                             ('parts', 'Demo Precision Components', 5),
                             ('tools', 'Demo Workshop Supplies', 3)]:
        suppliers[code] = find_or_create(store.suppliers(), 'name', name,
            lambda: store.save_supplier(name, code + '@example.invalid', terms='Sample: net 30 days',
                                        lead_days=lead, actor=ACTOR))
    locations = {}
    for name, kind in [('Demo assembly store', 'warehouse'), ('Demo coating partner', 'subcontractor')]:
        locations[name] = find_or_create(store.locations(), 'name', name,
                                        lambda: store.save_location(name, kind, actor=ACTOR))

    # code, description, unit, cost, selling price, opening, reorder, supplier, category
    rows = [
        ('SHEET', 'Mild steel sheet 2 mm', 'Kg', '68', '85', '500', '150', 'metal', 'Raw materials'),
        ('ROD', 'Stainless steel rod 12 mm', 'Kg', '210', '270', '60', '20', 'metal', 'Raw materials'),
        ('BOLT', 'M8 hex bolt', 'Pcs', '3', '5', '1200', '300', 'parts', 'Fasteners'),
        ('WIRE', 'MIG welding wire', 'Kg', '120', '155', '8', '10', 'tools', 'Consumables'),
        ('POWDER', 'Blue powder coating', 'Kg', '240', '320', '0', '10', 'tools', 'Consumables'),
        ('MOTOR', 'Geared motor 0.5 HP', 'Pcs', '4500', '6200', '0', '2', 'parts', 'Components'),
        ('BRACKET', 'Mounting bracket', 'Pcs', '0', '180', '0', '15', 'metal', 'Finished goods'),
        ('RACK', 'Fabricated rack', 'Pcs', '0', '2800', '0', '5', 'metal', 'Finished goods'),
        ('CRATE', 'Returnable transport crate', 'Pcs', '650', '850', '20', '5', 'tools', 'Returnables'),
        ('GLOVE', 'Industrial safety gloves', 'Pair', '45', '65', '12', '20', 'tools', 'Safety'),
        ('BEARING', 'Bearing 6204', 'Pcs', '180', '250', '25', '15', 'parts', 'Components'),
        ('DISC', 'Cutting disc 125 mm', 'Pcs', '55', '75', '18', '20', 'tools', 'Consumables'),
    ]
    products = {}
    for code, name, unit, cost, sale, opening, reorder, supplier, category in rows:
        sku = 'DEMO-' + code
        products[code] = find_or_create(store.products(), 'item_code', sku,
            lambda: store.save_product(dict(item_code=sku, item_name=name, unit=unit, category=category,
                barcode=sku, unit_price=cost, selling_price=sale, reorder_level=reorder, reorder_qty='50'),
                supplier_id=suppliers[supplier], opening=opening, actor=ACTOR, token=token('product-' + code)))
    p = products
    for code, tracking, attributes in [('POWDER', 'batch', {'Finish': 'Blue satin'}),
                                        ('MOTOR', 'serial', {'Power': '0.5 HP'})]:
        store.save_product_options(p[code], tracking, attributes, '', '0', actor=ACTOR)
    store.save_conversion(p['BOLT'], 'Box of 100', '100', actor=ACTOR)

    def batch(code, number, expiry='', warranty=''):
        return find_or_create(store.batches(p[code]), 'code', number,
            lambda: store.save_batch(p[code], number, expiry, warranty, actor=ACTOR))

    for number, expiry, qty in [('DEMO-COAT-A', day(15), '10'), ('DEMO-COAT-B', day(180), '20')]:
        bid = batch('POWDER', number, expiry)
        store.move_stock(p['POWDER'], 'receipt', qty, 'Sample coating lot', batch_id=bid,
                         actor=ACTOR, token=token(number))
    motors = []
    for n in range(1, 4):
        number = f'DEMO-MOTOR-{n:03d}'
        bid = batch('MOTOR', number, warranty=day(365))
        motors.append(bid)
        store.move_stock(p['MOTOR'], 'receipt', '1', 'Sample serialized motor', batch_id=bid,
                         actor=ACTOR, token=token(number))

    for code, qty, components, overhead in [
        ('BRACKET', '50', [('SHEET', '0.4'), ('BOLT', '4'), ('WIRE', '0.02')], '600'),
        ('RACK', '8', [('SHEET', '6'), ('BOLT', '20'), ('WIRE', '0.15')], '4000'),
    ]:
        store.save_recipe(p[code], [{'product_id': p[c], 'qty': q} for c, q in components], actor=ACTOR)
        store.assemble(p[code], qty, 1, 'DEMO-WO-' + code, overhead, actor=ACTOR, token=token('build-' + code))
    store.transfer(p['SHEET'], '80', 1, locations['Demo coating partner'], 'DEMO-DC-001',
                   actor=ACTOR, token=token('subcontractor'))
    store.transfer(p['BOLT'], '150', 1, locations['Demo assembly store'], 'DEMO-TRANSFER-001',
                   actor=ACTOR, token=token('assembly-store'))

    job_specs = [('Demo conveyor repair', 'Demo Sahyadri Engineering', '1500', 'ROD', '6'),
                 ('Demo machine guard fabrication', 'Demo Riverbend Packaging', '1000', 'SHEET', '25'),
                 ('Demo spare assembly', 'Demo Sahyadri Engineering', '3000', 'BEARING', '4')]
    for name, customer, budget, code, qty in job_specs:
        jid = find_or_create(store.jobs(), 'name', name,
                              lambda: store.save_job(name, customer, budget, actor=ACTOR))
        store.consume_job(jid, p[code], qty, 1, actor=ACTOR, token=token(name))
        store.add_attachment('job', jid, 'sample-job-card.txt',
                             f'SAMPLE JOB CARD\n{name}\nCustomer: {customer}\nInspect dimensions before dispatch.'.encode(), actor=ACTOR)

    for supplier, price, freight, lead in [('metal', '68', '450', 7), ('parts', '71', '200', 4)]:
        store.save_quote(suppliers[supplier], p['SHEET'], 'DEMO-QUOTE-' + supplier, price, '100',
                         freight, lead, day(30), 'Sample quote; payment within 30 days.',
                         actor=ACTOR, token=token('quote-' + supplier))

    orders = {}
    for code, qty, price, supplier, stage, received, due in [
        ('SHEET', '200', '68', 'metal', 'partial', '80', 3),
        ('WIRE', '50', '120', 'tools', 'draft', '0', 7),
        ('BEARING', '40', '180', 'parts', 'sent', '0', -3),
        ('DISC', '60', '55', 'tools', 'received', '60', -1),
    ]:
        oid = store.create_po(suppliers[supplier], [{'product_id': p[code], 'qty': qty, 'price': price}],
                              notes='Sample purchase: ' + stage, actor=ACTOR, token=token('po-' + code))
        orders[code] = oid
        order = store.order(oid)
        if stage != 'draft':
            if order['state'] == 'draft':
                store.approve_po(oid, actor=ACTOR, revision=order['revision'])
            if store.order(oid)['state'] == 'approved':
                store.place_manually(oid, 'DEMO confirmation ' + code, actor=ACTOR, revision=order['revision'])
            if received != '0':
                store.receive_po(oid, {order['lines'][0]['id']: received}, reference='DEMO-GRN-' + code,
                                 freight='150', actor=ACTOR, token=token('receive-' + code))
        store.set_order_due(oid, day(due), actor=ACTOR)
    for code, qty, price in [('DISC', '60', '55'), ('SHEET', '80', '72')]:
        oid = orders[code]
        bill = store.save_bill(oid, 'DEMO-BILL-' + code, day(0),
            [{'po_line_id': store.order(oid)['lines'][0]['id'], 'qty': qty, 'price': price}],
            freight='150', actor=ACTOR, token=token('bill-' + code))
        if code == 'DISC' and store.bill_match(bill)['state'] == 'review':
            store.accept_bill(bill, actor=ACTOR)

    customers = []
    for name, address in [('Demo Sahyadri Engineering', 'Sample customer, Pune'),
                           ('Demo Riverbend Packaging', 'Sample customer, Nashik'),
                           ('Demo Western Assembly Works', 'Sample customer, Satara')]:
        customers.append(find_or_create(store.customers(), 'name', name,
            lambda: store.save_customer(name, address, state='27', actor=ACTOR)))
    invoice_ids = []
    for n, lines, issued, due in [
        (0, [('BRACKET', '20', '180'), ('RACK', '2', '2800')], -14, -7),
        (1, [('RACK', '2', '2800')], -20, -5),
        (2, [('BRACKET', '10', '180'), ('MOTOR', '1', '6200')], -2, 14),
    ]:
        iid = store.issue_invoice(customers[n],
            [{'product_id': p[c], 'qty': qty, 'price': price, 'tax_rate': '0'} for c, qty, price in lines],
            1, day(issued), day(due), actor=ACTOR, token=token(f'invoice-{n}'))
        invoice_ids.append(iid)
    store.record_payment(invoice_ids[0], amount(store.invoice(invoice_ids[0])['total']), 'DEMO-PAID-001',
                         actor=ACTOR, token=token('payment-full'))
    store.record_payment(invoice_ids[1], '2000', 'DEMO-PART-002', actor=ACTOR, token=token('payment-part'))
    inv = store.invoice(invoice_ids[2])
    line = next(l for l in inv['lines'] if l['product_id'] == p['BRACKET'])
    store.credit_invoice(inv['id'], {line['id']: '2'}, 'Sample return: two brackets with finish damage',
                         actor=ACTOR, token=token('credit'))
    store.reserve(p['BRACKET'], '5', 1, 'DEMO next-week dispatch', actor=ACTOR, token=token('reserve'))
    loan = store.lend(p['CRATE'], '6', 1, 'Demo Sahyadri Engineering', day(-2), 'DEMO-RETURNABLE-001',
                      actor=ACTOR, token=token('loan'))
    store.return_loan(loan, '2', actor=ACTOR, token=token('loan-return'))
    store.save_repair(motors[0], 'Demo Western Assembly Works', 'Sample: motor runs noisily under load.',
                      actor=ACTOR, token=token('repair'))
    store.move_stock(p['GLOVE'], 'damage', '2', 'Sample safety inspection: damaged gloves',
                     actor=ACTOR, token=token('damage'))
    store.add_attachment('product', p['BRACKET'], 'sample-bracket-specification.txt',
                         b'SAMPLE SPECIFICATION\nMounting bracket\n2 mm mild steel, four M8 fixings, deburred edges.', actor=ACTOR)
    store.refresh_alerts()
    with store.connect(True) as db:
        state['complete'] = True
        db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(state), SEED_KEY))
    return True
