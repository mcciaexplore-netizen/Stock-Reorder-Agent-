st.title('Documents and scans')
entities={
    'purchase_order':{r['id']:r['number'] for r in store.orders()},
    'supplier_bill':{r['id']:r['number'] for r in store.bills()},
    'product':{r['id']:r['item_code']+' · '+r['item_name'] for r in products},
    'job':{r['id']:r['name'] for r in store.jobs()},
    'invoice':{r['id']:r['number'] for r in store.invoices()},
    'repair':{r['id']:r['code']+' · '+r['customer'] for r in store.repairs()},
}
entity=st.selectbox('Document belongs to',list(entities),format_func=lambda x:x.replace('_',' ').capitalize())
records=entities[entity]
if not records:st.info('Create a record in this category first.'); st.stop()
eid=st.selectbox('Linked record',list(records),format_func=records.get)
upload=st.file_uploader('Bill, delivery note, drawing or photograph',type=['pdf','png','jpg','jpeg','txt'])
with st.expander('Take a photograph'):
    photo=st.camera_input('Photograph document')
file=upload or photo
if file and st.button('Attach document',disabled=not store.allowed('documents')):
    act('attach',lambda:store.add_attachment(entity,eid,file.name,file.getvalue(),actor=actor),'Document attached.')
documents=store.attachments(entity,eid)
for doc in documents:
    with st.container(border=True):
        st.write(f'**{doc["filename"]}** · {doc["size"]:,} bytes · {doc["created_at"]}')
        st.download_button('Download',store.attachment_content(doc['id']),doc['filename'],doc['mime'],key=f'doc_{doc["id"]}')
        if doc['extracted_text']:
            st.text_area('Extracted text — check against original',value=doc['extracted_text'],height=220,key=f'extracted_{doc["id"]}')
        elif doc['mime'].startswith('image/'):
            if st.button('Read image text with local OCR',key=f'ocr_{doc["id"]}',disabled=not store.allowed('documents')):
                act('scan',lambda:store.scan_attachment(doc['id'],actor=actor),'Text extracted for review.')
st.caption('PDF text is extracted locally. Image OCR uses Windows text recognition or a locally configured Tesseract engine. Check the extracted text against the original before entering bill details.')
