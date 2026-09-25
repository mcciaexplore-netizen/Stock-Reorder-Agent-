from datetime import date,timedelta
st.title('Sales and invoices')
customers=store.customers(); customer_lookup={c['id']:c for c in customers}
with st.expander('Add or edit customer'):
    cid=st.selectbox('Customer record',[None]+list(customer_lookup),format_func=lambda i:'New customer' if i is None else customer_lookup[i]['name'])
    c=customer_lookup.get(cid,{})
    with st.form(f'customer_{cid}'):
        name=st.text_input('Customer name',value=c.get('name',''))
        address=st.text_area('Customer address',value=c.get('address',''))
        gst=st.text_input('Customer GSTIN (optional)',value=c.get('gstin',''))
        state=st.text_input('Customer state code',value=c.get('state_code',''))
        phone=st.text_input('Customer phone',value=c.get('phone',''))
        submit=st.form_submit_button('Save customer',disabled=not store.allowed('accounts'))
    if submit:act('customer',lambda:store.save_customer(name,address,gst,state,phone,actor=actor,customer_id=cid),'Customer saved.')
if customers and products:
    with st.expander('Create sales invoice / dispatch'):
        cid=st.selectbox('Bill to',list(customer_lookup),format_func=lambda i:customer_lookup[i]['name'])
        lid=pick_location('Dispatch from',key='invoice_location')
        ids=st.multiselect('Invoice products',list(product_lookup),format_func=product_label)
        if ids:
            with st.form(f'invoice_{cid}_{lid}_{ids}'):
                invoice_date=st.date_input('Invoice date',value=date.today())
                due=st.date_input('Payment due date',value=date.today()+timedelta(days=30))
                supply=st.text_input('Place of supply state code',value=customer_lookup[cid]['state_code'])
                lines=[]
                for pid in ids:
                    p=product_lookup[pid]; st.write(product_label(pid))
                    a,b,c=st.columns(3)
                    qty=a.text_input('Sold quantity',value='1',key=f'invoice_qty_{pid}')
                    price=b.text_input('Selling price (₹)',value=amount(p['selling_price']),key=f'invoice_price_{pid}')
                    tax=c.text_input('GST (%)',value=amount(p['tax_rate']),key=f'invoice_tax_{pid}')
                    batch=pick_batch(pid,lid,key=f'invoice_batch_{pid}',auto=True)
                    lines.append({'product_id':pid,'qty':qty,'price':price,'tax_rate':tax,'batch_id':batch})
                confirmed=st.checkbox('I checked the customer, tax treatment and goods being dispatched.')
                submit=st.form_submit_button('Issue invoice and dispatch goods',disabled=not store.allowed('accounts'))
            if submit:
                if not confirmed:st.error('Review and confirm the invoice before issuing.')
                else:act('invoice',lambda:store.issue_invoice(cid,lines,lid,invoice_date.isoformat(),due.isoformat(),supply,actor=actor,token=operation_key('invoice')),'Invoice issued and stock dispatched.')
invoices=store.invoices()
if not invoices:st.info('Issued invoices and credit notes will appear here.'); st.stop()
grid([{'Document':i['number'],'Customer':i['customer'],'Type':i['kind'],'Date':i['invoice_date'],
       'Total ₹':amount(i['total']),'Paid ₹':amount(i['paid']),'Credited ₹':amount(i['credited']),
       'Balance ₹':amount(i['total']-i['paid']-i['credited']) if i['kind']=='invoice' else ''} for i in invoices])
lookup={i['id']:i for i in invoices}
iid=st.selectbox('Open sales document',list(lookup),format_func=lambda i:lookup[i]['number'])
inv=store.invoice(iid)
grid([{'Product':l['description'],'Quantity':quantity(l['qty']),'Returned':quantity(l['returned']),'Unit price ₹':amount(l['price']),'GST %':amount(l['tax_rate'])} for l in inv['lines']])
st.download_button('Download printable invoice',store.invoice_document(iid),inv['number'].replace('/','-')+'.html','text/html')
st.caption('Open the downloaded document in a browser to print or save as PDF. Tax rates and place of supply are entered by your operator. Government e-invoice registration and return filing are separate integrations.')
if inv['kind']=='invoice':
    with st.expander('Record customer payment'):
        with st.form(f'payment_{iid}'):
            value=st.text_input('Amount received (₹)')
            ref=st.text_input('Payment reference')
            submit=st.form_submit_button('Record payment',disabled=not store.allowed('accounts'))
        if submit:act('payment',lambda:store.record_payment(iid,value,ref,actor=actor,token=operation_key('payment')),'Payment recorded.')
    with st.expander('Return goods and issue credit note'):
        with st.form(f'credit_{iid}'):
            returns={l['id']:st.text_input(f'{l["description"]} return quantity (line {l["id"]})',value='0',key=f'return_{l["id"]}') for l in inv['lines'] if l['returned']<l['qty']}
            reason=st.text_input('Customer return reason')
            submit=st.form_submit_button('Receive return and issue credit note',disabled=not store.allowed('accounts'))
        if submit:act('credit',lambda:store.credit_invoice(iid,returns,reason,actor=actor,token=operation_key('credit')),'Return received and linked credit note issued.')

st.divider()
with st.expander('🏷️ Dispatch Package QR Label Generator'):
    import urllib.parse
    st.write('Generate printable dispatch package QR label for this invoice:')
    dispatch_data = {
        "invoice_no": inv['number'],
        "customer": inv['customer'],
        "date": inv['invoice_date'],
        "total_items": len(inv['lines']),
        "total_amount_inr": amount(inv['total']),
        "contents": [{"item": l['description'], "qty": quantity(l['qty'])} for l in inv['lines']]
    }
    encoded_inv = urllib.parse.quote(json.dumps(dispatch_data))
    qr_dispatch_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={encoded_inv}"
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.image(qr_dispatch_url, caption=f"Dispatch Tag: {inv['number']}", width=180)
    with col_b:
        st.markdown(f"**Dispatch Label for Invoice {inv['number']}**")
        st.write(f"Customer: **{inv['customer']}**")
        st.write(f"Package items: **{len(inv['lines'])} line items**")
        st.json(dispatch_data)

