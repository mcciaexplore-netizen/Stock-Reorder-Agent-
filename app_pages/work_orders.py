from datetime import date, timedelta
import json

st.title('Work orders')
st.caption('Plan an internal job, assign responsibility, consume materials into work in progress and record output in parts.')
if products:
    with st.expander('Plan a work order'):
        pid=pick_product('Work-order finished product',key='wo_product')
        lid=pick_location('Work-order location',key='wo_location')
        links={}
        for o in store.sales_orders():
            if o['state'] not in ('confirmed','partial'):continue
            for l in store.sales_order(o['id'])['lines']:
                if l['product_id']==pid:links[l['id']]=f'{o["number"]} · {o["customer"]}'
        with st.form(f'wo_create_{pid}_{lid}'):
            order_line=st.selectbox('Linked customer commitment',[None]+list(links),format_func=lambda i:links.get(i,'Make to stock'))
            a,b=st.columns(2)
            qty=a.text_input('Planned output quantity',value='1')
            operator=b.text_input('Assigned operator')
            due=st.date_input('Work due date',value=date.today()+timedelta(days=7))
            stages=st.text_input('Work stages, separated by commas',value='Preparation, Processing, Assembly, Final check')
            overhead=st.text_input('Planned labour, machine and overhead total ₹',value='0')
            notes=st.text_area('Work instructions')
            submit=st.form_submit_button('Create work order',disabled=not store.allowed('inventory'))
        if submit:act('wo_create',lambda:store.create_work_order(pid,qty,lid,operator,due.isoformat(),[s.strip() for s in stages.split(',')],notes,overhead,order_line,actor=actor,token=operation_key('wo_create')),'Work order planned with a saved copy of its recipe.')
orders=store.work_orders()
if not orders:st.info('Create a recipe in Assembly and jobs, then plan your first work order.'); st.stop()
grid([{'Work order':w['number'],'Product':w['item_name'],'Operator':w['operator'],'Stage':json.loads(w['stages'])[w['stage_index']],
    'Status':w['state'],'Due':w['due_date'],'Planned':quantity(w['planned']),'Completed':quantity(w['completed']),'Unit':w['unit'],
    'Overdue':w['due_date']<date.today().isoformat() and w['state'] not in ('completed','cancelled')} for w in orders])
lookup={w['id']:w for w in orders}; wid=st.selectbox('Open work order',list(lookup),format_func=lambda i:lookup[i]['number'])
w=store.work_order_detail(wid); stages=json.loads(w['stages'])
a,b,c=st.columns(3)
a.metric('Remaining output',quantity(w['planned']-w['completed']))
b.metric('Work in progress ₹',amount(w['wip_value']))
c.metric('Actual job cost ₹',amount(w['total']))
grid([{'Material':r['item_name'],'Planned':quantity(r['planned_qty']),'Consumed into WIP':quantity(r['actual']),'Scrap included':quantity(r['scrap']),'Unit':r['unit']} for r in w['materials']])
if w['state'] not in ('completed','cancelled'):
    with st.expander('Release / update work progress',expanded=w['state']=='planned'):
        with st.form(f'wo_stage_{wid}_{w["stage_index"]}'):
            stage=st.selectbox('Current or next work stage',list(range(w['stage_index'],min(w['stage_index']+2,len(stages)))),format_func=lambda i:stages[i])
            operator=st.text_input('Operator responsible',value=w['operator'])
            due=st.date_input('Revised work due',value=date.fromisoformat(w['due_date']))
            note=st.text_input('Progress / delay note')
            submit=st.form_submit_button('Release / save progress',disabled=not store.allowed('inventory'))
        if submit:act('wo_stage',lambda:store.advance_work_order(wid,stage,operator,due.isoformat(),note,actor=actor),'Work progress updated.')
    if w['state']!='planned':
        with st.expander('Consume materials into work in progress'):
            st.caption('Record actual material used. Finished output will use these costs; do not also record the same work on the quick assembly screen.')
            with st.form(f'wo_materials_{wid}'):
                quantities={r['product_id']:st.text_input(f'{r["item_name"]} quantity to consume · {r["unit"]}',value='0',key=f'wo_use_{wid}_{r["product_id"]}') for r in w['materials']}
                submit=st.form_submit_button('Consume work-order materials',disabled=not store.allowed('inventory'))
            if submit:act('wo_materials',lambda:store.issue_work_materials(wid,quantities,actor=actor,token=operation_key('wo_materials')),'Materials consumed and their stock cost moved into WIP.')
        with st.expander('Record labour, machine or overhead cost'):
            with st.form(f'wo_cost_{wid}'):
                kind=st.selectbox('Cost type',['labour','machine','overhead'])
                hours=st.text_input('Hours (labour / machine)',value='1')
                rate=st.text_input('Hourly rate / total overhead amount ₹',value='0')
                note=st.text_input('Cost description')
                submit=st.form_submit_button('Add actual job cost',disabled=not store.allowed('inventory'))
            if submit:act('wo_cost',lambda:store.record_work_cost(wid,kind,hours,rate,note,actor=actor,token=operation_key('wo_cost')),'Actual cost added to work in progress.')
        with st.expander('Complete partial or final output'):
            batch=pick_batch(w['product_id'],w['location_id'],key=f'wo_output_batch_{wid}')
            with st.form(f'wo_complete_{wid}'):
                qty=st.text_input('Quantity completed now',value='1')
                note=st.text_area('Completion / material variance explanation')
                checked=st.checkbox('Materials, scrap and costs for this output have been recorded.')
                submit=st.form_submit_button('Record output for quality inspection',disabled=not store.allowed('inventory'))
            if submit:
                if not checked:st.error('Review the recorded materials, scrap and costs before completing output.')
                else:act('wo_output',lambda:store.complete_work_output(wid,qty,batch,note,actor=actor,token=operation_key('wo_output')),'Output recorded in quarantine. Release it through Quality checks.')
            st.caption('Partial output receives a proportional share of current WIP cost. Final completion receives the remaining cost and closes the order.')
    with st.expander('Cancel an unstarted work order'):
        with st.form(f'wo_cancel_{wid}'):
            reason=st.text_input('Work-order cancellation reason')
            cancel=st.form_submit_button('Cancel work order',disabled=not store.allowed('inventory'))
        if cancel:act('wo_cancel',lambda:store.cancel_work_order(wid,reason,actor=actor),'Work order cancelled.')
st.caption('Use Cost analysis to record scrap / recoverable items and compare planned and actual consumption.')
