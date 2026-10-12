import streamlit as st

PAGES = {}


def register(pages):
    PAGES.update(pages)


def go(name):
    st.switch_page(PAGES[name])


def link(name, label=None, icon=None):
    page = PAGES[name]
    st.page_link(page, label=label or page.title, icon=icon, width="stretch")
