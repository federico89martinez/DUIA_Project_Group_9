"""Interfaz de prueba en Streamlit.

Uso (desde la raíz del proyecto):
    streamlit run src/app.py        # se abre en http://localhost:8501
"""
import sys
import uuid
from pathlib import Path

# Streamlit ejecuta este archivo como script: hay que agregar la raíz del proyecto al path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import db
from src.config import DB_PATH
from src.graph import conversar

if not DB_PATH.exists():  # primera ejecución: crea la base de datos
    db.init_db()

st.set_page_config(page_title="Asistente de vestuario", page_icon="👔", layout="wide")

EJEMPLOS = {
    "✅ Caso típico": (
        "Voy a un casamiento de noche en verano. Uso talle 50 y tengo un pantalón negro. "
        "Busco un saco que combine."
    ),
    "❓ Dato faltante": "Quiero un saco para una fiesta",
    "⚠️ Restricción incumplida": (
        "Voy a un casamiento de noche en verano, talle 56, tengo un pantalón negro. "
        "Mi presupuesto es de $120.000 como máximo."
    ),
    "🔍 Evidencia insuficiente": (
        "Necesito un disfraz de dinosaurio inflable para un cumpleaños infantil de verano, talle 50"
    ),
}
RUTAS = {
    "recomendar": "✅ Recomendación verificada contra la base de datos",
    "diagnosticar": "⚠️ Sin combinación viable: identifica la restricción y pregunta",
    "pedir_datos": "❓ Faltan datos: los pide antes de buscar",
    "sin_evidencia": "🔍 Evidencia insuficiente: no inventa una recomendación",
}


def nueva_conversacion() -> None:
    st.session_state.thread_id = str(uuid.uuid4())  # el estado del grafo se guarda por thread_id
    st.session_state.historial = []
    st.session_state.ultimo = None


def mostrar(texto: str) -> None:
    # Streamlit interpreta "$...$" como fórmula matemática: se escapa para que los precios se vean bien.
    st.markdown(texto.replace("$", "\\$"))


def estado_candidato(e: dict) -> str:
    if e["descartado"]:
        return "descartado por vos"
    if not e["temporada_ok"]:
        return f"temporada: {e['temporada']}"
    if not e["stock_ok"]:
        return "sin stock en tu talle"
    if not e["precio_ok"]:
        return "supera el presupuesto"
    return "✓ viable"


if "thread_id" not in st.session_state:
    nueva_conversacion()

# ── Barra lateral: casos de prueba ──
entrada_ejemplo = None
with st.sidebar:
    st.header("Probar casos")
    st.caption("Cada botón inicia una conversación nueva.")
    for etiqueta, texto in EJEMPLOS.items():
        if st.button(etiqueta, use_container_width=True):
            nueva_conversacion()
            entrada_ejemplo = texto
    st.divider()
    if st.button("🗑️ Nueva conversación", use_container_width=True):
        nueva_conversacion()
        st.rerun()

st.title("👔 Asistente de vestuario para fiestas")

# ── Procesar el mensaje (antes de dibujar, para que todo se vea actualizado) ──
entrada = st.chat_input("Contame qué evento tenés, tu talle y qué prendas ya tenés...") or entrada_ejemplo
if entrada:
    st.session_state.historial.append(("user", entrada))
    try:
        with st.spinner("Pensando..."):
            resultado = conversar(entrada, st.session_state.thread_id)
        st.session_state.historial.append(("assistant", resultado["respuesta"]))
        st.session_state.ultimo = resultado
    except Exception as error:  # por ejemplo, límite de uso de la API o clave faltante
        st.session_state.historial.append(("assistant", f"⚠️ Ocurrió un error: {error}"))

# ── Pantalla: chat a la izquierda, detalle del sistema a la derecha ──
col_chat, col_info = st.columns([3, 2])

with col_chat:
    if not st.session_state.historial:
        st.info("Escribí tu pedido abajo o usá un caso de prueba de la barra lateral.")
    for rol, texto in st.session_state.historial:
        with st.chat_message(rol):
            mostrar(texto)

with col_info:
    st.subheader("🔎 Qué hizo el sistema")
    ultimo = st.session_state.ultimo
    if ultimo is None:
        st.caption("Acá vas a ver las preferencias detectadas y los productos verificados en cada turno.")
    else:
        st.write(RUTAS.get(ultimo["ruta"], ultimo["ruta"]))
        st.caption("Preferencias detectadas (se mantienen entre turnos)")
        st.json(ultimo["prefs"])
        trabajo = ultimo["trabajo"]
        if trabajo.get("consulta"):
            st.caption("Consulta enviada al RAG")
            st.code(trabajo["consulta"], language=None)
        if trabajo.get("guias"):
            st.caption("Guías de estilo recuperadas")
            for g in trabajo["guias"]:
                st.write(f"**{g['id']}** (similitud {g['score']})")
        if trabajo.get("evaluados"):
            st.caption("Candidatos verificados en la base de datos")
            st.dataframe(
                [
                    {
                        "ID": e["id"], "Producto": e["nombre"], "Similitud": e["score"],
                        "Stock": e["unidades"], "Precio": e["precio"], "Estado": estado_candidato(e),
                    }
                    for e in trabajo["evaluados"]
                ],
                hide_index=True,
                use_container_width=True,
            )
