from datetime import date, timedelta

st.title('Advanced job-work tracking')
st.caption('Track ownership, outward and inward challans, partial returns and material still held by each subcontractor.')
customers={c['id']:c for c in store.customers()}
with st.expander('Open a job-work order'):
    with st.form('jw_create'):
        owner=st.selectbox('Material ownership',['company','customer'])
        cid=st.selectbox('Material owner / customer',[None]+list(customers),format_func=lambda i:customers[i]['name'] if i else 'Company-owned / no customer')
        party=st.text_input('Subcontractor / processing site')
        lid=pick_location('Sending / receiving warehouse',key='jw_location')
        due=st.date_input('Expected material return',value=date.today()+timedelta(days=14))
        ref=st.text_input('Customer / job-work reference')
        submit=st.form_submit_button('Create job-work order',disabled=not store.allowed('inventory'))
    if submit:act('jw_create',lambda:store.create_jobwork(owner,cid,party,lid,due.isoformat(),ref,actor=actor,token=operation_key('jw_create')),'Job-work order opened.')
orders=store.jobwork_orders()
if not orders:st.info('Open a job-work order to receive customer material or send company material.'); st.stop()
grid([{'Job work':j['number'],'Material owner':j['customer'] if j['owner']=='customer' else 'Company','Subcontractor':j['subcontractor'],
    'Return due':j['due_date'],'Status':j['state'],'Overdue':j['state']=='open' and j['due_date']<date.today().isoformat()} for j in orders])
lookup={j['id']:j for j in orders}; jid=st.selectbox('Open job-work order',list(lookup),format_func=lambda i:lookup[i]['number']); j=lookup[jid]
if j['owner']=='customer':st.info('These materials remain customer-owned. Custody records do not add to company stock or inventory value.')
else:st.info('Company material stays in inventory at a dedicated subcontractor location. Use this screen for all returns and reconciliation.')
if j['state']=='open' and products:
    with st.expander('Receive customer material' if j['owner']=='customer' else 'Send company material to subcontractor'):
        pid=pick_product('Job-work material',key='jw_product'); batch=pick_batch(pid,j['location_id'],key='jw_batch')
        with st.form(f'jw_material_{jid}_{pid}_{batch}'):
            qty=st.text_input('Material quantity',value='1')
            ref=st.text_input('Incoming customer challan' if j['owner']=='customer' else 'Outward challan / transport reference')
            submit=st.form_submit_button('Record material challan',disabled=not store.allowed('inventory'))
        if submit:act('jw_material',lambda:store.receive_jobwork_material(jid,pid,qty,ref,batch,actor=actor,token=operation_key('jw_material')),'Material and challan recorded.')
materials=store.jobwork_materials(jid)
if materials:
    grid([{'Line':m['id'],'Product':m['item_name'],'Batch':m['batch'] or '', 'Total received / sent':quantity(m['qty']),
        'At subcontractor':quantity(m['outside']),'Customer material on site':quantity(m['onsite']),'Returned to owner':quantity(m['returned']),
        'Consumed':quantity(m['consumed']),'Scrap':quantity(m['scrap']),'Unit':m['unit']} for m in materials])
    if j['state']=='open':
        byid={m['id']:m for m in materials}
        with st.expander('Partial return / material reconciliation',expanded=True):
            with st.form(f'jw_reconcile_{jid}'):
                mid=st.selectbox('Material challan line',list(byid),format_func=lambda i,byid=byid:f'{i} · {byid[i]["item_name"]}')
                actions=['send','return','customer_return','consume','scrap'] if j['owner']=='customer' else ['return','consume','scrap']
                labels={'send':'Send to processing site','return':'Receive partial return from processing site','customer_return':'Return on-site material to customer','consume':'Record material consumed at processing site','scrap':'Record scrap at processing site'}
                action=st.selectbox('Material action',actions,format_func=lambda a:labels[a])
                qty=st.text_input('Reconciliation quantity',value='1')
                ref=st.text_input('Return challan / reconciliation reference')
                submit=st.form_submit_button('Record job-work movement',disabled=not store.allowed('inventory'))
            if submit:act('jw_reconcile',lambda:store.reconcile_jobwork(mid,action,qty,ref,actor=actor,token=operation_key('jw_reconcile')),'Job-work balances and challan updated.')
challans=store.jobwork_challans(jid)
if challans:
    with st.expander('Challan history and downloads'):
        grid([{'Challan':e['number'],'Date':e['created_at'],'Action':e['action'].replace('_',' '),'Product':e['item_name'],'Quantity':quantity(e['qty']),'Unit':e['unit'],'Reference':e['reference']} for e in challans])
        byid={e['id']:e for e in challans}; eid=st.selectbox('Download challan',list(byid),format_func=lambda i:byid[i]['number'])
        st.download_button('Download material record',store.jobwork_document(eid),byid[eid]['number']+'.html','text/html')
        st.download_button('Export reconciliation history',csv_bytes(challans),'job-work-history.csv','text/csv')
if j['state']=='open' and st.button('Close fully reconciled job work',disabled=not store.allowed('inventory')):
    act('jw_close',lambda:store.close_jobwork(jid,actor=actor),'Job-work order closed.')
