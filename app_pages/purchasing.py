from datetime import date,timedelta
st.title('Quotations and supplier bills')
section=st.radio('Purchasing workspace',['Quotations and price history','Supplier bill verification'],key='purchasing_section')
if section=='Quotations and price history':
    pid=pick_product(key='quote_product')
    qty=st.text_input('Compare for quantity',value='1')
    try:quotes=store.quotes(pid,qty)
    except ValidationError as exc:
        st.error(str(exc)); quotes=[]
    if quotes:
        grid([{'Reference':q['reference'],'Supplier':q['supplier'],'Unit price ₹':amount(q['price']),'Minimum':quantity(q['min_qty']),
            'Compare quantity':quantity(q['comparison_qty']),'Total with freight ₹':amount(q['comparison_total']),'Lead days':q['lead_days'],
            'Valid until':q['valid_until'],'Expired':q['expired'],'Terms':q['terms']} for q in quotes])
        valid={q['id']:q for q in quotes if not q['expired']}
        if valid:
            with st.form('quote_order'):
                qid=st.selectbox('Use quotation',list(valid),format_func=lambda i:f'{valid[i]["supplier"]} · {valid[i]["reference"]}')
                order_qty=st.text_input('Quantity to order',value=qty)
                submit=st.form_submit_button('Create draft from quotation',disabled=not store.allowed('purchase'))
            if submit:act('quote_order',lambda:store.order_quote(qid,order_qty,actor=actor,token=operation_key('quote_order')),'Draft created. Review it in Purchase orders.')
    if suppliers:
        with st.expander('Record supplier quotation'):
            with st.form(f'quote_{pid}'):
                sid=st.selectbox('Quoted by',list(supplier_lookup),format_func=supplier_label)
                ref=st.text_input('Quotation reference')
                price=st.text_input('Quoted price per stock unit (₹)',value=amount(product_lookup[pid]['unit_price']))
                minimum=st.text_input('Quoted minimum quantity',value='1')
                freight=st.text_input('Quoted freight (₹)',value='0')
                lead=st.number_input('Delivery lead time (days)',min_value=0,max_value=3650,value=7)
                valid_until=st.date_input('Quotation valid until',value=date.today()+timedelta(days=30))
                terms=st.text_area('Quoted payment and delivery terms')
                submit=st.form_submit_button('Save quotation',disabled=not store.allowed('purchase'))
            if submit:act('quote',lambda:store.save_quote(sid,pid,ref,price,minimum,freight,lead,valid_until.isoformat(),terms,actor=actor,token=operation_key('quote')),'Quotation saved.')
    st.subheader('Supplier price history')
    history=store.price_history(pid)
    if history:grid([dict(h,price=amount(h['price']),qty=quantity(h['qty'])) for h in history])
    else:st.info('Quotations and placed orders will appear here.')
else:
    orders={o['id']:o for o in store.orders() if o['state'] in ('sent','partial','received','cancelled')}
    bills=store.bills()
    if bills:grid([{'Bill':b['number'],'Order':b['po_number'],'Supplier':b['supplier_name'],'Date':b['bill_date'],'Status':b['state']} for b in bills])
    action=st.selectbox('Bill action',['Record new bill','Review or correct existing bill'])
    current=None
    if action=='Review or correct existing bill':
        if not bills:st.info('No supplier bills yet.'); st.stop()
        lookup={b['id']:b for b in bills}
        bid=st.selectbox('Supplier bill',list(lookup),format_func=lambda i:f'{lookup[i]["number"]} · {lookup[i]["supplier_name"]}')
        current=store.bill_match(bid)
        grid([{'SKU':l['item_code'],'Ordered':quantity(l['ordered']),'Received':quantity(l['received']),
               'Previously billed':quantity(l['previously_billed']),'This bill':quantity(l['qty']),
               'Agreed price ₹':amount(l['agreed']),'Billed price ₹':amount(l['price']),
               'Landed unit cost ₹':amount(l['landed_unit_paise'])} for l in current['lines']])
        st.metric('Bill total',inr(amount(current['total'])))
        for issue in current['issues']:st.warning(issue)
        if not current['issues']:st.success('Billed quantities and prices match the order and received goods.')
        if current['state']=='review':
            reviewed=st.checkbox('I checked the bill, taxes, charges and received goods.')
            if st.button('Accept verified bill',disabled=not reviewed or bool(current['issues']) or not store.allowed('accounts')):
                act('accept_bill',lambda:store.accept_bill(bid,actor=actor),'Bill accepted.')
        else:
            st.info('This bill has been accepted and is preserved in accounting exports.')
            st.stop()
    if not orders:st.info('Place a purchase order before recording a supplier bill.'); st.stop()
    oid=current['po_id'] if current else st.selectbox('Bill for order',list(orders),format_func=lambda i:orders[i]['number'])
    order=store.order(oid)
    st.subheader('Correct bill' if current else 'Record supplier bill')
    with st.form(f'bill_{oid}_{current["id"] if current else "new"}'):
        number=st.text_input('Supplier invoice number',value=current['number'] if current else '')
        bdate=st.date_input('Supplier invoice date',value=date.fromisoformat(current['bill_date']) if current else date.today())
        previous={l['po_line_id']:l for l in current['lines']} if current else {}
        lines=[]
        for l in order['lines']:
            left,right=st.columns(2)
            q=left.text_input(f'{l["item_name"]} billed quantity',value=quantity(previous.get(l['id'],{}).get('qty',l['received'])),key=f'bill_qty_{oid}_{l["id"]}')
            price=right.text_input(f'{l["item_name"]} billed price (₹)',value=amount(previous.get(l['id'],{}).get('price',l['price'])),key=f'bill_price_{oid}_{l["id"]}')
            lines.append({'po_line_id':l['id'],'qty':q,'price':price})
        freight=st.text_input('Total freight / handling (₹)',value=amount(current['freight']) if current else '0')
        tax=st.text_input('Total tax on supplier bill (₹)',value=amount(current['tax']) if current else '0')
        submit=st.form_submit_button('Save bill for verification',disabled=not store.allowed('accounts'))
    if submit:
        from inventory import scaled
        def save_bill():
            nonzero=[l for l in lines if scaled(l['qty'])]
            return store.save_bill(oid,number,bdate.isoformat(),nonzero,freight,tax,actor=actor,token=operation_key('bill'),bill_id=current['id'] if current else None)
        act('bill',save_bill,'Bill saved for verification.')
    st.caption('Bills do not receive goods or change stock cost again. Enter actual freight when receiving goods; this screen allocates bill charges for comparison.')
