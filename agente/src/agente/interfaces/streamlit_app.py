"""Interfaz de chat web con Streamlit (adaptador delgado sobre AgentService).

Ejecutar:
    streamlit run src/agente/interfaces/streamlit_app.py

No forma parte del núcleo: solo instancia la fachada y llama a sus métodos.
Pensada para crecer de forma sencilla (estética aparte): añadir paneles,
métricas o controles es solo añadir widgets aquí, sin tocar el núcleo.
"""

from __future__ import annotations

import streamlit as st

from agente.core.types import AgentResult, StepType
from agente.errors import AgenteError
from agente.service.agent_service import AgentService


@st.cache_resource(show_spinner=False)
def get_service() -> AgentService:
    """Una sola instancia de servicio por proceso del servidor."""
    return AgentService()


def ensure_session(service: AgentService) -> str:
    """Una sesión del agente por sesión de navegador."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = service.create_session()
        st.session_state.history = []  # lista de (role, text) para mostrar
    return st.session_state.session_id


def render_sidebar(service: AgentService) -> None:
    with st.sidebar:
        st.header("Agente")
        st.caption(f"Modelo: `{service.settings.model}`")
        st.caption(f"Máx. pasos: {service.settings.max_steps}")
        st.write("**Herramientas**")
        for name in service.list_tools():
            st.write(f"- `{name}`")

        if not service.settings.has_api_key:
            st.warning("Falta `AGENTE_MINIMAX_API_KEY`. Defínela en `.env`.")

        if st.button("Nueva conversación", use_container_width=True):
            service.close_session(st.session_state.get("session_id", ""))
            st.session_state.pop("session_id", None)
            st.session_state.pop("history", None)
            st.rerun()


def render_trace(result: AgentResult) -> None:
    """Panel de observabilidad: pasos, herramientas y tokens."""
    label = f"Traza · {len(result.steps)} pasos · {result.usage.total_tokens} tokens"
    with st.expander(label):
        for step in result.steps:
            if step.type is StepType.TOOL:
                ok = "✅" if step.detail.get("ok") else "❌"
                st.markdown(
                    f"{ok} **herramienta** `{step.detail.get('tool')}` "
                    f"· args: `{step.detail.get('arguments')}`"
                )
                st.code(step.detail.get("result", ""), language="text")
            else:
                calls = step.detail.get("tool_calls") or []
                if calls:
                    st.markdown(f"🧠 **razona** → pide: {[c['name'] for c in calls]}")
                elif step.detail.get("content"):
                    st.markdown("🧠 **respuesta final**")
        if not result.completed:
            st.error(result.error or "No completado.")


def main() -> None:
    st.set_page_config(page_title="Agente", page_icon="🤖")
    st.title("🤖 Agente orquestador")

    service = get_service()
    session_id = ensure_session(service)
    render_sidebar(service)

    # Repintar el historial visible.
    for role, text in st.session_state.history:
        with st.chat_message(role):
            st.markdown(text)

    prompt = st.chat_input("Escribe una tarea…")
    if not prompt:
        return

    st.session_state.history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando…"):
            try:
                result = service.run_task(session_id, prompt)
            except AgenteError as exc:
                st.error(f"Error del agente: {exc}")
                return
            except Exception as exc:  # noqa: BLE001 — mostrar cualquier fallo en la UI
                st.error(f"Error inesperado: {exc}")
                return

        output = result.output if result.completed else f"⚠️ {result.error}"
        st.markdown(output)
        render_trace(result)

    st.session_state.history.append(("assistant", output))


main()
