import json
from datetime import date
st.title('Tracking and units')
pid=pick_product(key='tracked_product'); p=product_lookup[pid]
st.caption('Use a separate SKU for each variant. Custom fields can describe size, colour, grade, drawing number or any business-specific attribute.')
with st.form(f'options_{pid}_{p["version"]}'):
    tracking=st.selectbox('Stock tracking',['none','batch','serial'],index=['none','batch','serial'].index(p['tracking']))
    attrs=st.text_area('Custom fields (one name=value per line)',value='\n'.join(f'{k}={v}' for k,v in json.loads(p['attributes']).items()))
    hsn=st.text_input('HSN code',value=p['hsn'])
    tax=st.text_input('GST rate (%)',value=amount(p['tax_rate']))
    minimum=st.text_input('Minimum purchase quantity',value=quantity(p['min_order']))
    pack=st.text_input('Purchase pack size',value=quantity(p['pack_size']))
    safety=st.text_input('Safety stock',value=quantity(p['safety_stock']))
    submit=st.form_submit_button('Save tracking and purchase rules',disabled=not store.allowed('catalogue'))
if submit:
    def save_options():
        fields={}
        for line in attrs.splitlines():
            if not line.strip():continue
            if '=' not in line:raise ValidationError('Write each custom field as name=value.')
            k,v=line.split('=',1)
            if k.strip() in fields:raise ValidationError('Custom field names must be unique.')
            fields[k.strip()]=v.strip()
        store.save_product_options(pid,tracking,fields,hsn,tax,minimum,pack,safety,actor=actor)
    act('options',save_options,'Product tracking and purchase rules saved.')
st.subheader('Alternate units')
conversions=store.conversions(pid)
if conversions:grid([{'Unit':c['unit'],'Base units':quantity(c['factor'])} for c in conversions])
with st.form(f'conversion_{pid}'):
    unit=st.text_input('Alternate unit (for example Box)')
    factor=st.text_input(f'Number of {p["unit"]} in one alternate unit',value='1')
    submit=st.form_submit_button('Save conversion',disabled=not store.allowed('catalogue'))
if submit:act('conversion',lambda:store.save_conversion(pid,unit,factor,actor=actor),'Unit conversion saved.')
if p['tracking']!='none':
    st.subheader('Batches and serial numbers')
    batches=store.batches(pid)
    if batches:grid([dict(b,stock=quantity(b['stock'])) for b in batches])
    with st.form(f'batch_{pid}'):
        code=st.text_input('Batch / serial number')
        expiry=st.text_input('Expiry date (YYYY-MM-DD, optional)')
        warranty=st.text_input('Warranty until (YYYY-MM-DD, optional)')
        submit=st.form_submit_button('Create batch / serial',disabled=not store.allowed('inventory'))
    if submit:act('batch',lambda:store.save_batch(pid,code,expiry,warranty,actor=actor),'Batch / serial created. Record its stock receipt next.')
    st.caption('Receipts require a selected batch or serial. Dispatch can select the earliest unexpired batch automatically. Receive serials one at a time.')
