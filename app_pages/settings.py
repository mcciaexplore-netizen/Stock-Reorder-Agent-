from security import ROLES
st.title('Settings')
if not store.allowed('admin'):
    st.info('An owner manages business settings and user access.')
    st.stop()
with st.form('business_settings'):
    name=st.text_input('Business name',value=business.get('business_name',''))
    address=st.text_area('Business address',value=business.get('business_address',''))
    gst=st.text_input('Business GSTIN (optional)',value=business.get('gstin',''))
    state=st.text_input('Business state code',value=business.get('state_code',''))
    budget=st.text_input('Monthly purchase approval budget (₹, 0 means unlimited)',value=business.get('monthly_budget','0'))
    backups=st.checkbox('Enable automatic local backups',value=business.get('backup_enabled')=='true')
    days=st.number_input('Days between backups',min_value=1,max_value=30,value=int(business.get('backup_days','1')))
    language=st.selectbox('Default navigation language',['English','Hindi'],index=int(business.get('language')=='Hindi'))
    submit=st.form_submit_button('Save business settings',type='primary')
if submit:
    act('settings',lambda:store.save_settings({'business_name':name,'business_address':address,'gstin':gst,'state_code':state,
        'monthly_budget':budget,'backup_enabled':str(backups).lower(),'backup_days':str(days),'default_industry':'manufacturing','language':language},actor=actor),'Business settings saved.')
st.caption('Backups run while an owner has the app open, or through the supplied maintenance worker. Backups are stored beside the database in a backups folder. Copy important backups to another device.')
if st.button('Run backup and exception check now'):
    act('maintenance',lambda:store.run_maintenance(actor=actor),lambda result:result)
st.subheader('Users and permissions')
users=store.users(); grid(users)
lookup={u['id']:u for u in users}
uid=st.selectbox('User record',[None]+list(lookup),format_func=lambda i:'Add user' if i is None else lookup[i]['username'])
u=lookup.get(uid,{})
with st.form(f'user_{uid}'):
    username=st.text_input('Username',value=u.get('username',''))
    display=st.text_input('Name',value=u.get('name',''))
    role=st.selectbox('Role',list(ROLES),index=list(ROLES).index(u.get('role','viewer')))
    password=st.text_input('New password (12+ characters; blank keeps current password)',type='password')
    active=st.checkbox('Active user',value=bool(u.get('active',1)))
    submit=st.form_submit_button('Save user')
if submit:act('user',lambda:store.save_user(username,display,role,password,active,actor=actor,user_id=uid),'User saved. Existing sessions for this user have been signed out.')
st.caption('Owner: all actions. Manager: catalogue, stock, purchasing and accounts. Purchaser: drafts and quotations. Warehouse: stock and production. Accountant: bills and sales. Viewer: read-only. All users belong to this one business.')
