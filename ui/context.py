from dataclasses import dataclass

import streamlit as st

from growth_os.service import GrowthService


@st.cache_resource(show_spinner=False)
def get_service():
    return GrowthService()


@dataclass
class Ctx:
    service: GrowthService
    user: str
    client_id: str
    profile: object
    clients: list


def current():
    service = get_service()
    user = st.session_state["active_user"]
    clients = service.clients(user)
    client_id = st.session_state.get("active_client")
    profile = next((client for client in clients if client.id == client_id), None)
    return Ctx(service=service, user=user, client_id=client_id, profile=profile, clients=clients)


def client_names(ctx):
    return {client.id: client.name for client in ctx.clients}


def client_scope(ctx, key, label="Client", include_all=True):
    names = client_names(ctx)
    options = (["__all__"] if include_all else []) + list(names)
    default = ctx.client_id if ctx.client_id in names else options[0]
    chosen = st.selectbox(
        label,
        options,
        index=options.index(default),
        format_func=lambda cid: "All my clients" if cid == "__all__" else names[cid],
        key=f"{key}-scope-{ctx.client_id}",
    )
    return None if chosen == "__all__" else chosen
