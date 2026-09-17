"""ASGI entry point detected by Vercel's Python runtime."""
from pathlib import Path
import streamlit as st
from deployment_errors import handle_script_error

app = st.App(Path(__file__).with_name('streamlit_app.py'), on_script_error=handle_script_error)
