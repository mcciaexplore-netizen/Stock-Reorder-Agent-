st.title('Exceptions inbox')
store.refresh_alerts()
alerts=store.alerts()
show=st.checkbox('Include acknowledged items')
visible=[a for a in alerts if show or not a['acknowledged']]
st.metric('Needs attention',sum(not a['acknowledged'] for a in alerts))
for a in visible:
    with st.container(border=True):
        st.write(f'**{a["category"]}**')
        st.write(a['message'])
        st.caption(a['created_at'])
        if not a['acknowledged'] and st.button('Acknowledge',key='ack_'+a['key'],disabled=not store.allowed('documents')):
            act('ack',lambda:store.acknowledge_alert(a['key'],actor=actor),'Exception acknowledged.')
if not visible:st.success('No unacknowledged exceptions.')
st.caption('Acknowledgement records that an item was seen. It does not resolve the underlying stock, bill or delivery issue. Changed issues return to this inbox.')
