import json
from offline import entry_sheet
st.title('Offline stock entry')
st.write('Download an entry sheet for a phone or laptop. It stores movements on that device until you export and upload its queue here.')
st.download_button('Download offline entry sheet',entry_sheet(products,locations,business['workspace_id'],store.batches()),'stocklist-offline.html','text/html')
st.caption('Open the downloaded HTML file in a browser. Existing SKUs and locations are included. Keyboard barcode scanners work in the SKU field; camera scanning depends on the browser. Refresh the sheet after catalogue changes.')
upload=st.file_uploader('Upload offline movement queue',type=['json'])
if upload:
    try:
        if upload.size>2*1024*1024:raise ValidationError('Queue file must be smaller than 2 MB.')
        rows=json.loads(upload.getvalue())
        if not isinstance(rows,list) or len(rows)>1000 or any(not isinstance(r,dict) for r in rows):raise ValidationError('Upload a list of at most 1,000 movements.')
        grid(rows)
        confirmed=st.checkbox('I checked the queued movements and want to apply them to current stock.')
        if st.button('Apply reviewed queue',disabled=not confirmed or not store.allowed('inventory')):
            result=store.sync_movements(rows,actor=actor)
            st.session_state['offline_results']=result
        if 'offline_results' in st.session_state:
            grid(st.session_state['offline_results'])
            st.download_button('Download import results',csv_bytes(st.session_state['offline_results']),'offline_results.csv','text/csv')
            st.caption('Rows needing review did not change stock. Applied transaction IDs cannot apply twice, even if the same queue is uploaded again.')
    except (ValueError,ValidationError) as exc:
        st.error(str(exc))
