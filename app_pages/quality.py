st.title('Quality checks')
st.caption('Hold stock for checking, record acceptance or rejection, and release reworked stock after reinspection.')
if products:
    with st.expander('Start incoming / work / final check'):
        pid=pick_product('Stock item to check',key='qc_product')
        lid=pick_location('Inspection stock location',key='qc_location')
        batch=pick_batch(pid,lid,key='qc_batch')
        with st.form(f'qc_open_{pid}_{lid}_{batch}'):
            stage=st.selectbox('Check stage',['incoming','production','final'],format_func=lambda s:'work' if s=='production' else s)
            qty=st.text_input('Quantity to quarantine',value='1')
            ref=st.text_input('Receipt / work / dispatch reference')
            submit=st.form_submit_button('Hold stock for checking',disabled=not store.allowed('inventory'))
        if submit:act('qc_open',lambda:store.open_quality_inspection(pid,lid,qty,stage,ref,batch,actor=actor,token=operation_key('qc_open')),'Stock quarantined. It cannot be sold, transferred or consumed until released.')
checks=store.quality_inspections()
if not checks:st.info('Incoming receipts can be held for checking. Work-order output enters final check automatically.'); st.stop()
grid([{'Inspection':f'QC-{q["id"]}','Product':q['item_name'],'Stage':q['stage'],'State':q['state'],'Location':q['location'],
    'Batch':q['batch'] or '', 'Inspected quantity':quantity(q['qty']),'Accepted':quantity(q['accepted']),'Held':quantity(q['held']),
    'Disposed':quantity(q['disposed']),'Unit':q['unit'],'Reference':q['reference']} for q in checks])
lookup={q['id']:q for q in checks}; qid=st.selectbox('Open quality check',list(lookup),format_func=lambda i:f'QC-{i} · {lookup[i]["item_name"]}')
q=lookup[qid]
if q['state'] in ('awaiting','rework'):
    with st.form(f'qc_result_{qid}_{q["accepted"]}'):
        st.write(f'Quantity awaiting decision: {quantity(q["held"])} {q["unit"]}')
        a,b=st.columns(2)
        accepted=a.text_input('Accepted quantity',value='0')
        rejected=b.text_input('Rejected quantity',value=quantity(q['held']))
        notes=st.text_area('Check observations / measurements')
        submit=st.form_submit_button('Save check and release accepted stock',disabled=not store.allowed('inventory'))
    if submit:act('qc_result',lambda:store.record_quality_result(qid,accepted,rejected,notes,actor=actor,token=operation_key('qc_result')),'Check recorded. Accepted stock released; rejected stock remains blocked.')
if q['state']=='rejected':
    with st.form(f'qc_rework_{qid}'):
        notes=st.text_area('Rework instructions')
        submit=st.form_submit_button('Send rejected quantity for rework',disabled=not store.allowed('inventory'))
    if submit:act('qc_rework',lambda:store.route_quality_rework(qid,notes,actor=actor),'Rework recorded. Complete recheck before release.')
if q['state'] in ('rejected','rework'):
    with st.expander('Dispose of rejected stock'):
        with st.form(f'qc_dispose_{qid}'):
            qty=st.text_input('Rejected quantity to dispose',value='0')
            reason=st.text_input('Disposal reason')
            submit=st.form_submit_button('Record rejected stock disposal',disabled=not store.allowed('inventory'))
        if submit:act('qc_dispose',lambda:store.dispose_quality_stock(qid,qty,reason,actor=actor,token=operation_key('qc_dispose')),'Rejected stock disposed with a stock-ledger entry.')
history=store.quality_history(qid)
if history:
    st.subheader('Check history')
    grid([{'Date':r['created_at'],'Action':r['action'],'Accepted':quantity(r['accepted']),'Rejected / disposed':quantity(r['rejected']),'Observations':r['notes'],'Checked by':r['actor']} for r in history])
