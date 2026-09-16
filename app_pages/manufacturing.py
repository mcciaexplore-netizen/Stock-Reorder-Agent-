st.title('Assembly and jobs')
section=st.radio('Operations workspace',['Assembly / kits','Jobs and material consumption'],key='manufacturing_section')
if section=='Assembly / kits':
    pid=pick_product('Finished product / kit',key='finished_product')
    recipe=store.recipes(pid)
    if recipe:grid([{'Component':r['item_name'],'SKU':r['item_code'],'Quantity per finished unit':quantity(r['qty']),'Unit':r['unit']} for r in recipe])
    with st.expander('Edit bill of materials'):
        ids=st.multiselect('Components',[i for i in product_lookup if i!=pid],default=[r['component_id'] for r in recipe],format_func=product_label)
        if ids:
            existing={r['component_id']:r['qty'] for r in recipe}
            with st.form(f'recipe_{pid}_{ids}'):
                components=[{'product_id':cid,'qty':st.text_input(f'{product_label(cid)} per one finished unit',value=quantity(existing.get(cid,1000)),key=f'bom_{pid}_{cid}')} for cid in ids]
                save=st.form_submit_button('Save bill of materials',disabled=not store.allowed('catalogue'))
            if save:act('recipe',lambda:store.save_recipe(pid,components,actor=actor),'Bill of materials saved.')
    if recipe:
        st.subheader('Record completed assembly / kit')
        lid=pick_location('Assembly location',key='production_location')
        batch=pick_batch(pid,lid,key='production_batch')
        with st.form(f'assemble_{pid}'):
            qty=st.text_input('Finished quantity',value='1')
            overhead=st.text_input('Total labour / subcontracting / overhead cost (₹)',value='0')
            reference=st.text_input('Assembly job / batch reference')
            submit=st.form_submit_button('Record assembly',disabled=not store.allowed('inventory'))
        if submit:act('assemble',lambda:store.assemble(pid,qty,lid,reference,overhead,batch,actor=actor,token=operation_key('assemble')),lambda cost:f'Assembly recorded. Output cost ₹{amount(cost)}.')
        st.caption('Components are consumed together, and finished stock receives their cost plus overhead. This can represent a kit, bundle, repair set, service job or production run.')
else:
    jobs=store.jobs()
    if jobs:grid([{'Job':j['name'],'Customer':j['customer'],'Material cost ₹':amount(j['material_cost']),'Budget ₹':amount(j['budget'])} for j in jobs])
    with st.expander('Create job'):
        with st.form('job'):
            name=st.text_input('Job name / number')
            customer=st.text_input('Customer / project')
            budget=st.text_input('Material budget (₹, 0 means no limit)',value='0')
            submit=st.form_submit_button('Create job',disabled=not store.allowed('catalogue'))
        if submit:act('job',lambda:store.save_job(name,customer,budget,actor=actor),'Job created.')
    if jobs and products:
        with st.form('job_use'):
            lookup={j['id']:j for j in jobs}
            jid=st.selectbox('Job',list(lookup),format_func=lambda i:lookup[i]['name'])
            pid=pick_product(key='job_product')
            lid=pick_location(key='job_location')
            qty=st.text_input('Consumed quantity',value='1')
            submit=st.form_submit_button('Record material consumption',disabled=not store.allowed('inventory'))
        if submit:act('job_use',lambda:store.consume_job(jid,pid,qty,lid,actor=actor,token=operation_key('job_use')),lambda cost:f'Material use recorded at ₹{amount(cost)}.')
    st.caption('Use job consumption for materials used on services, projects or field work. Assembly already consumes its bill of materials; do not record those same components twice.')
