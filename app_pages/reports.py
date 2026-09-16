st.title('Reports and accounting export')
report=store.reports()
section=st.selectbox('Report',['Stock valuation','Slow / non-moving stock','Invoice margins','Supplier delivery performance','Job costs'])
if section in ('Stock valuation','Slow / non-moving stock'):
    rows=report['stock'] if section=='Stock valuation' else report['dead_stock']
    formatted=[{'SKU':r['item_code'],'Product':r['item_name'],'Location':r['location'],'Stock':quantity(r['qty']),
        'Unit':r['unit'],'Stock cost ₹':amount(r['value']),'Used in 30 days':quantity(r['used_30_days']),'Last outgoing':r['last_outgoing']} for r in rows]
    st.metric('Recorded stock cost',inr(amount(sum(r['value'] for r in rows))))
    st.caption('Moving weighted-average cost by location. Upgraded opening stock uses the product purchase price at upgrade; subsequent receipts use recorded costs. No use in 30 days is a review signal, not proof the item is obsolete.')
elif section=='Invoice margins':
    formatted=[{'Document':r['number'],'Type':r['kind'],'Date':r['invoice_date'],'Customer':r['customer'],
        'Net sales ₹':amount(r['subtotal']*(-1 if r['kind']=='credit' else 1)),
        'Stock cost ₹':amount(r['cost']*(-1 if r['kind']=='credit' else 1)),
        'Gross margin ₹':amount(r['margin']*(-1 if r['kind']=='credit' else 1))} for r in report['margins']]
elif section=='Supplier delivery performance':
    formatted=report['suppliers']
else:
    formatted=[{'Job':j['name'],'Customer':j['customer'],'Material cost ₹':amount(j['material_cost']),
        'Budget ₹':amount(j['budget']),'Remaining budget ₹':amount(j['budget']-j['material_cost'])} for j in store.jobs()]
if formatted:
    grid(formatted)
    st.download_button('Export this report',csv_bytes(formatted),section.lower().replace(' ','_').replace('/','-')+'.csv','text/csv')
else:st.info('No records for this report yet.')
st.subheader('Accounting handoff')
st.download_button('Download sales, credits and accepted supplier bills',store.accounting_export(),'accounting_documents.csv','text/csv')
st.caption('Generic CSV export for your accountant or accounting import mapping. This does not submit GST returns or connect to an accounting provider.')
