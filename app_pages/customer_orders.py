from datetime import date, timedelta

st.title('Customer quotations and sales orders')
st.caption('Agree delivery commitments, dispatch in parts, then invoice each delivery once.')
customers={c['id']:c for c in store.customers()}
if not customers:st.info('Add a customer on Sales and invoices to prepare a quotation.')
if customers and products:
    with st.expander('Prepare customer quotation'):
        cid=st.selectbox('Quote for',list(customers),format_func=lambda i:customers[i]['name'])
        ids=st.multiselect('Quoted products',list(product_lookup),format_func=product_label)
        with st.form(f'customer_quote_{cid}_{ids}'):
            a,b=st.columns(2)
            valid=a.date_input('Quote valid until',value=date.today()+timedelta(days=30))
            due=b.date_input('Promised delivery',value=date.today()+timedelta(days=14))
            lines=[]
            for pid in ids:
                st.write(product_label(pid)); a,b,c=st.columns(3)
                qty=a.text_input('Quoted quantity',value='1',key=f'cq_qty_{pid}')
                price=b.text_input('Unit selling price ₹',value=amount(product_lookup[pid]['selling_price']),key=f'cq_price_{pid}')
                tax=c.text_input('Tax rate %',value=amount(product_lookup[pid]['tax_rate']),key=f'cq_tax_{pid}')
                lines.append(dict(product_id=pid,qty=qty,price=price,tax_rate=tax))
            notes=st.text_area('Quotation terms and notes')
            save=st.form_submit_button('Save customer quotation',disabled=not store.allowed('accounts'))
        if save:act('cq_create',lambda:store.create_customer_quote(cid,lines,valid.isoformat(),due.isoformat(),notes,actor=actor,token=operation_key('cq_create')),'Customer quotation saved.')
quotes=store.customer_quotes()
if quotes:
    with st.expander('Customer quotations',expanded=not store.sales_orders()):
        grid([{'Quote':q['number'],'Customer':q['customer'],'Valid until':q['valid_until'],'Delivery':q['delivery_date'],'Status':q['state']} for q in quotes])
        lookup={q['id']:q for q in quotes}
        qid=st.selectbox('Open quotation',list(lookup),format_func=lambda i,lookup=lookup:lookup[i]['number'])
        st.download_button('Download quotation',store.customer_document('quote',qid),lookup[qid]['number']+'.html','text/html')
        if lookup[qid]['state']=='open':
            if st.button('Confirm as sales order',type='primary',disabled=not store.allowed('accounts')):
                act('cq_confirm',lambda:store.confirm_customer_quote(qid,actor=actor,token=operation_key('cq_confirm')),'Sales order confirmed. Stock changes only on dispatch.')
            if st.button('Cancel quotation',disabled=not store.allowed('accounts')):
                act('cq_cancel',lambda:store.cancel_customer_quote(qid,actor=actor),'Quotation cancelled.')
orders=store.sales_orders()
if not orders:st.info('Confirmed customer orders will appear here.'); st.stop()
grid([{'Order':o['number'],'Customer':o['customer'],'Delivery due':o['delivery_date'],'Status':o['state'],
    'Overdue':o['delivery_date']<date.today().isoformat() and o['state'] in ('confirmed','partial')} for o in orders])
lookup={o['id']:o for o in orders}; oid=st.selectbox('Open customer order',list(lookup),format_func=lambda i:f'{lookup[i]["number"]} · {lookup[i]["customer"]}')
order=store.sales_order(oid)
grid([{'Product':l['item_name'],'Ordered':quantity(l['qty']),'Dispatched':quantity(l['dispatched']),'Pending':quantity(l['qty']-l['dispatched']),'Unit':l['unit'],'Price ₹':amount(l['price'])} for l in order['lines']])
st.download_button('Download sales order',store.customer_document('order',oid),order['number']+'.html','text/html')
if order['state'] in ('confirmed','partial'):
    with st.expander('Dispatch against this order'):
        lid=pick_location('Delivery from',key='so_location')
        with st.form(f'so_dispatch_{oid}'):
            quantities={l['id']:st.text_input(f'{l["item_name"]} dispatch quantity · {l["unit"]}',value='0',key=f'so_dispatch_qty_{l["id"]}') for l in order['lines'] if l['qty']>l['dispatched']}
            ref=st.text_input('Delivery / transport reference')
            dispatched=st.date_input('Actual dispatch date',value=date.today(),max_value=date.today())
            submit=st.form_submit_button('Record partial or full delivery',disabled=not store.allowed('inventory'))
        if submit:act('so_dispatch',lambda:store.dispatch_sales_order(oid,quantities,lid,ref,dispatched.isoformat(),actor=actor,token=operation_key('so_dispatch')),'Delivery recorded. Pending quantities updated; the delivery is ready to invoice.')
    with st.expander('Change delivery commitment / cancel balance'):
        with st.form(f'so_due_{oid}'):
            due=st.date_input('Revised delivery date',value=date.fromisoformat(order['delivery_date']))
            reason=st.text_input('Commitment change reason')
            save=st.form_submit_button('Save customer commitment',disabled=not store.allowed('accounts'))
            cancel=st.form_submit_button('Cancel remaining order',disabled=not store.allowed('accounts'))
        if save:act('so_due',lambda:store.set_sales_commitment(oid,due.isoformat(),reason,actor=actor),'Delivery commitment updated.')
        if cancel:act('so_cancel',lambda:store.cancel_sales_order(oid,reason,actor=actor),'Remaining commitment cancelled. Existing deliveries remain recorded.')
deliveries=store.sales_dispatches(oid)
if deliveries:
    st.subheader('Delivery notes and invoicing')
    grid([{'Delivery':d['number'],'Date':d['dispatch_date'],'Reference':d['reference'],'Invoice':d['invoice_id'] or 'Awaiting invoice'} for d in deliveries])
    byid={d['id']:d for d in deliveries}; did=st.selectbox('Delivery note',list(byid),format_func=lambda i:byid[i]['number'])
    st.download_button('Download delivery note',store.customer_document('delivery',did),byid[did]['number']+'.html','text/html')
    if not byid[did]['invoice_id']:
        with st.form(f'delivery_invoice_{did}'):
            issued=st.date_input('Delivery invoice date',value=date.today())
            payable=st.date_input('Payment due',value=date.today()+timedelta(days=30))
            submit=st.form_submit_button('Invoice this delivery',disabled=not store.allowed('accounts'))
        if submit:act('delivery_invoice',lambda:store.invoice_sales_dispatch(did,issued.isoformat(),payable.isoformat(),actor=actor,token=operation_key('delivery_invoice')),'Delivery invoiced. View the invoice on Sales and invoices.')
    st.caption('Delivery invoicing uses the agreed prices and delivered quantities. It does not issue stock again. Credit returns do not reopen the original commitment.')
