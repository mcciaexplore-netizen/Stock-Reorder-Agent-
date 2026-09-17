"""Recoverable connection errors for the deployed Streamlit entry point."""
import sqlite3
import streamlit as st


def handle_script_error(error):
    if not isinstance(error, (sqlite3.Error, OSError)):
        return False
    st.error('The database or a required file is temporarily unavailable. Reload the page to try again. If you submitted a change, check its status before repeating it.')
    return True
