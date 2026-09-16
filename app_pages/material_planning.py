from datetime import date, timedelta

st.title('Material requirements planning')
st.caption('Identify item and material shortages from confirmed customer commitments and open work orders.')
horizon=st.date_input('Plan commitments due through',value=date.today()+timedelta(days=30))
try:
    plan=store.material_plan(horizon.isoformat())
except ValidationError as exc:
    st.error(str(exc)); st.stop()
if not plan:st.info('Confirm a customer order or create a work order to see material requirements.'); st.stop()
a,b,c=st.columns(3)
a.metric('Products needing purchase',len({r['product_id'] for r in plan if r['shortage'] and r['action']=='Buy'}))
b.metric('Products needing assembly',len({r['product_id'] for r in plan if r['shortage'] and r['action']=='Make'}))
c.metric('Demand lines',len(plan))
only=st.checkbox('Show shortages only',value=True)
rows=[{'Product':r['product'],'SKU':r['item_code'],'Demand source':r['source'],'Required by':r['due_date'],'Unit':r['unit'],
    'Gross requirement':quantity(r['gross']),'Allocated free stock':quantity(r['from_stock']),'Dated purchases':quantity(r['incoming']),
    'Scheduled output':quantity(r['scheduled_output']),'Shortage':quantity(r['shortage']),'Action':r['action'],
    'Later purchases':quantity(r['late_incoming']),'Undated purchases':quantity(r['undated_incoming'])} for r in plan if not only or r['shortage']]
grid(rows)
st.download_button('Export material plan',csv_bytes(rows),'material-requirements.csv','text/csv')
st.info('Stock is allocated once across all demands. Reserved, quarantined, expired and externally held stock is excluded. Only placed purchases due by the requirement date count as incoming supply.')
with st.expander('How this plan is calculated'):
    st.write('Confirmed sales orders contribute their undelivered quantities. Open work orders contribute unconsumed materials from their saved recipe and scheduled finished output. Uncovered make requirements expand through recipe levels.')
    st.write('This is a stock and material plan, not a capacity schedule. All internal warehouses are pooled; arrange transfers to the work location. Work-order materials are planned by the work-order due date. Purchases with no delivery date appear separately and do not reduce shortages.')
    st.write('Create purchase drafts on Purchase orders and work plans on Work orders after reviewing these recommendations.')
