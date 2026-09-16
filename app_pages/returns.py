from datetime import date,timedelta
st.title('Returnables and repairs')
section=st.radio('Service workspace',['Returnable containers / equipment','Serial-number repairs'],key='service_section')
if section=='Returnable containers / equipment':
    loans=store.loans()
    if loans:grid([{'ID':r['id'],'Item':r['item_name'],'Held by':r['holder'],'Sent':quantity(r['qty']),'Returned':quantity(r['returned']),'Due':r['due_date'],'Reference':r['reference']} for r in loans])
    if products:
        pid=pick_product(key='loan_product'); lid=pick_location('Dispatch location',key='loan_location')
        batch=pick_batch(pid,lid,key='loan_batch')
        with st.form('loan'):
            qty=st.text_input('Quantity to lend',value='1')
            holder=st.text_input('Held by customer / contractor')
            due=st.date_input('Return due',value=date.today()+timedelta(days=7))
            ref=st.text_input('Returnable delivery reference')
            submit=st.form_submit_button('Record returnable dispatch',disabled=not store.allowed('inventory'))
        if submit:act('loan',lambda:store.lend(pid,qty,lid,holder,due.isoformat(),ref,actor=actor,token=operation_key('loan'),batch_id=batch),'Returnable stock dispatched.')
    opened={r['id']:r for r in loans if r['returned']<r['qty']}
    if opened:
        with st.form('return_loan'):
            loan=st.selectbox('Outstanding returnable',list(opened),format_func=lambda i:f'{opened[i]["holder"]} · {opened[i]["item_name"]} · {opened[i]["reference"]}')
            qty=st.text_input('Quantity returned now',value='1')
            submit=st.form_submit_button('Receive returnable',disabled=not store.allowed('inventory'))
        if submit:act('return_loan',lambda:store.return_loan(loan,qty,actor=actor,token=operation_key('return_loan')),'Returnable received.')
else:
    repairs=store.repairs()
    if repairs:grid(repairs)
    serials={b['id']:b for b in store.batches() if b['tracking']=='serial'}
    if serials:
        with st.form('repair'):
            bid=st.selectbox('Serial number',list(serials),format_func=lambda i:f'{serials[i]["item_code"]} · {serials[i]["code"]} · warranty: {serials[i]["warranty_until"] or "not recorded"}')
            customer=st.text_input('Repair customer')
            problem=st.text_area('Reported fault')
            submit=st.form_submit_button('Open repair job',disabled=not store.allowed('inventory'))
        if submit:act('repair',lambda:store.save_repair(bid,customer,problem,actor=actor,token=operation_key('repair')),'Repair job opened.')
    else:st.info('Register serial-tracked products on Tracking and units first.')
    opened={r['id']:r for r in repairs if r['state']=='open'}
    if opened:
        with st.form('close_repair'):
            rid=st.selectbox('Open repair',list(opened),format_func=lambda i:f'{opened[i]["code"]} · {opened[i]["customer"]}')
            resolution=st.text_area('Repair outcome')
            submit=st.form_submit_button('Close repair',disabled=not store.allowed('inventory'))
        if submit:act('close_repair',lambda:store.close_repair(rid,resolution,actor=actor),'Repair closed.')
    st.caption('Repair records track service status. Customer-owned repairs are not added to saleable inventory.')
