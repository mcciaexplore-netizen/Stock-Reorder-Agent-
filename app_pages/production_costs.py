st.title('Scrap and cost analysis')
st.caption('Compare planned allowances with actual consumption, labour, machine time and recovered value.')
orders=store.work_orders()
if not orders:st.info('Plan a work order to start tracking costs.'); st.stop()
lookup={w['id']:w for w in orders}; wid=st.selectbox('Cost analysis for work order',list(lookup),format_func=lambda i:f'{lookup[i]["number"]} · {lookup[i]["item_name"]}')
w=store.work_order_detail(wid)
if w['state'] not in ('completed','cancelled'):
    with st.expander('Record scrap / recoverable offcuts'):
        components={r['product_id']:r for r in w['materials']}
        pid=st.selectbox('Consumed material scrapped',list(components),format_func=product_label)
        recovered=st.selectbox('Recoverable offcut product',[None]+list(product_lookup),format_func=lambda i:product_label(i) if i else 'No recoverable stock')
        batch=pick_batch(recovered,w['location_id'],key='scrap_recovery_batch') if recovered else None
        with st.form(f'wo_scrap_{wid}_{pid}_{recovered}'):
            qty=st.text_input('Scrap quantity within material already consumed',value='0')
            reason=st.text_input('Scrap cause / reason')
            recovered_qty=st.text_input('Recoverable output quantity',value='0')
            value=st.text_input('Total recovery value ₹',value='0')
            submit=st.form_submit_button('Record scrap and recovery',disabled=not store.allowed('inventory'))
        if submit:act('wo_scrap',lambda:store.record_work_scrap(wid,pid,qty,reason,recovered,recovered_qty,value,batch,actor=actor,token=operation_key('wo_scrap')),'Scrap recorded. Recoverable output added to stock and credited against WIP.')
        st.caption('Scrap is a portion of material already consumed, so recording it does not deduct the raw material a second time. Recovery value transfers cost from WIP to the recoverable product.')
a,b,c=st.columns(3)
a.metric('Planned total ₹',amount(w['planned_cost']))
b.metric('Actual net cost ₹',amount(w['total']))
c.metric('Actual minus planned ₹',amount(w['total']-w['planned_cost']))
grid([{'Cost component':label,'Amount ₹':amount(w[key])} for key,label in [('material','Consumed materials'),('labour','Labour'),('machine','Machine'),('overhead','Other overhead'),('recovery','Recovery credit'),('output_value','Allocated finished output'),('wip_value','Remaining work in progress')]])
st.metric('Allocated cost per completed unit ₹',amount(w['unit_output_cost']))
if w['committed_net_revenue'] is not None:
    st.metric('Committed order value for this job ₹',amount(w['committed_net_revenue']))
    st.metric('Committed value minus recorded job costs ₹',amount(w['committed_net_revenue']-w['total']))
    st.caption('This comparison uses the linked order price before tax. It is not realised profit: unfinished costs, discounts, returns and unrecorded business expenses can change the final margin.')
rows=[{'Material':r['item_name'],'Planned for whole job':quantity(r['planned_qty']),'Actual consumed':quantity(r['actual']),
    'Variance':quantity(r['actual']-r['planned_qty']),'Scrap within consumption':quantity(r['scrap']),'Unit':r['unit']} for r in w['materials']]
st.subheader('Planned versus actual material consumption')
grid(rows); st.download_button('Export material cost comparison',csv_bytes(rows),'work-order-consumption.csv','text/csv')
if w['state']!='completed':st.caption('This job is still open. Actual consumption and costs are cumulative to date; planned values cover the full job.')
if w['costs']:
    st.subheader('Labour, machine and overhead entries')
    grid([{'Date':c['created_at'],'Type':c['kind'],'Hours':quantity(c['hours']) if c['kind']!='overhead' else '', 'Rate / amount ₹':amount(c['rate']),'Cost ₹':amount(c['cost']),'Description':c['note']} for c in w['costs']])
if w['scrap_records']:
    st.subheader('Scrap and recovery history')
    grid([{'Date':s['created_at'],'Material':product_label(s['product_id']),'Scrap':quantity(s['qty']), 'Reason':s['reason'],
        'Recovered product':product_label(s['recovered_product_id']) if s['recovered_product_id'] else '',
        'Recovered quantity':quantity(s['recovered_qty']),'Recovery value ₹':amount(s['recovery_value'])} for s in w['scrap_records']])
