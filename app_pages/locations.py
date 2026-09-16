st.title('Locations and reservations')
stock=store.location_stock()
if stock:
    rows=[{'Location':r['location'],'SKU':r['item_code'],'Product':r['item_name'],'On hand':quantity(r['qty']),
        'Reserved':quantity(r['reserved']),'Quality hold':quantity(r['held']),'Available':quantity(r['available']),'Unit':r['unit'],'Stock cost ₹':amount(r['value'])} for r in stock]
    grid(rows)
    st.download_button('Export location stock',csv_bytes(rows),'location_stock.csv','text/csv')
with st.expander('Add a warehouse, shop or external stock location'):
    with st.form('location'):
        name=st.text_input('Location name')
        kind=st.selectbox('Location type',['warehouse','shop','subcontractor','consignment'])
        contact=st.text_input('Contact / address')
        save=st.form_submit_button('Save location',disabled=not store.allowed('catalogue'))
    if save:act('location',lambda:store.save_location(name,kind,contact,actor=actor),'Location saved.')
if products:
    st.subheader('Transfer owned stock')
    st.caption('Stock at a subcontractor or consignee remains owned stock. Each transfer carries its recorded cost.')
    pid=pick_product(key='transfer_product')
    source=pick_location('From location',key='transfer_source')
    destination=pick_location('To location',key='transfer_dest')
    bid=pick_batch(pid,source,key='transfer_batch',auto=True)
    with st.form('transfer'):
        qty=st.text_input('Transfer quantity',value='1')
        ref=st.text_input('Transfer / delivery note reference')
        submit=st.form_submit_button('Transfer stock',disabled=not store.allowed('inventory'))
    if submit:act('transfer',lambda:store.transfer(pid,qty,source,destination,ref,actor=actor,token=operation_key('transfer'),batch_id=bid),'Stock transferred.')
    st.subheader('Reserve stock for an order or job')
    with st.form('reserve'):
        pid=pick_product(key='reserve_product')
        lid=pick_location(key='reserve_location')
        qty=st.text_input('Reserve quantity',value='1')
        ref=st.text_input('Order / job reference')
        submit=st.form_submit_button('Reserve stock',disabled=not store.allowed('inventory'))
    if submit:act('reserve',lambda:store.reserve(pid,qty,lid,ref,actor=actor,token=operation_key('reserve')),'Stock reserved.')
reservations=store.reservations()
if reservations:
    grid([dict(r,qty=quantity(r['qty'])) for r in reservations])
    opened={r['id']:r for r in reservations if r['state']=='open'}
    if opened:
        with st.form('close_reservation'):
            rid=st.selectbox('Open reservation',list(opened),format_func=lambda i:f'{opened[i]["item_code"]} · {opened[i]["reference"]}')
            fulfill=st.checkbox('Dispatch this stock now (otherwise only release the reservation)')
            submit=st.form_submit_button('Close reservation',disabled=not store.allowed('inventory'))
        if submit:act('close_reservation',lambda:store.release_reservation(rid,actor=actor,fulfill=fulfill),'Reservation closed.')
