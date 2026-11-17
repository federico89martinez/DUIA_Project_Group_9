"""Grafo de LangGraph: el flujo completo del asistente de vestuario.

Flujo (cada recuadro es un nodo; los rombos son decisiones):

    extraer_preferencias ──◇ ¿faltan datos? ── sí ─► pedir_datos ─► FIN
            │ no
            ▼
    buscar_candidatos ──◇ ¿hay evidencia? ── no ─► sin_evidencia ─► FIN
            │ sí
            ▼
    verificar_disponibilidad ──◇ ¿hay algo viable? ── sí ─► recomendar ─► FIN
                                      │ no
                                      ▼
                                 diagnosticar ─► FIN   (pregunta qué cambio acepta)

Reparto de tareas:
  - LLM:    entender el mensaje (extraer_preferencias) y redactar la explicación (recomendar).
  - Código: validar, buscar, verificar stock/precio/talle y decidir. Los datos de la
            ficha final (ID, talle, precio, stock) los agrega el código, no el LLM.

Estado: el checkpointer guarda el estado por conversación (thread_id), así que
si el usuario pide una alternativa o cambia una preferencia, el contexto se mantiene.

Uso (desde la raíz del proyecto):
    python -m src.graph            # corre 4 conversaciones de ejemplo
    python -m src.graph mermaid    # imprime el diagrama del grafo
"""
import json
import sys
from functools import lru_cache
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from src import db, rag
from src.config import GROQ_MODEL

try:
    from langgraph.checkpoint.memory import InMemorySaver as Checkpointer
except ImportError:  # versiones anteriores de langgraph
    from langgraph.checkpoint.memory import MemorySaver as Checkpointer


# ─────────────────────────────── Estado ───────────────────────────────

class Estado(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # historial de la conversación
    prefs: dict                  # preferencias acumuladas (evento, talle, presupuesto, ...)
    descartados: list[str]       # IDs que el usuario pidió no volver a ver
    ultima_recomendacion: str    # ID del último producto recomendado
    trabajo: dict                # resultados intermedios del turno actual (para depurar y evaluar)


# Datos sin los cuales no se puede recomendar. El presupuesto es opcional (None = sin tope).
REQUERIDOS = {
    "evento": "el tipo de evento",
    "temporada": "la época del año (verano o invierno)",
    "talle_saco": "tu talle de saco",
}


class Extraccion(BaseModel):
    """Datos que el usuario dio o cambió en su ÚLTIMO mensaje."""

    evento: str | None = Field(None, description="Tipo de evento, por ejemplo 'casamiento de noche'.")
    temporada: Literal["verano", "invierno", "cualquiera"] | None = Field(
        None, description="Época del año. 'cualquiera' si acepta cualquier temporada."
    )
    talle_saco: str | None = Field(None, description="Talle de saco, por ejemplo '50'.")
    presupuesto_max: int | None = Field(
        None, description="Presupuesto máximo en pesos argentinos, solo el número (150000, no '150 mil')."
    )
    sin_tope_presupuesto: bool = Field(False, description="True si dice que no tiene límite de presupuesto.")
    prendas_propias: list[str] = Field(
        default_factory=list,
        description="Prendas que el usuario YA tiene y mencionó en este mensaje, por ejemplo ['pantalón negro'].",
    )
    pedido: str | None = Field(None, description="Qué busca, por ejemplo 'un saco que combine con mi pantalón'.")
    pide_alternativa: bool = Field(False, description="True si pide otra opción distinta de la última recomendada.")


PROMPT_EXTRACCION = """Extraés datos de un pedido de vestuario para una fiesta.

Datos que ya conocemos del usuario (JSON): {prefs}

Últimos mensajes de la conversación:
{historial}

Devolvé SOLO lo que el usuario dijo o cambió en su ÚLTIMO mensaje. Para todo lo demás
usá null (o lista vacía / false). No repitas datos ya conocidos ni inventes nada."""

PROMPT_EXPLICACION = """Sos un asesor de una tienda de ropa. Escribí en español rioplatense, de 2 a 4 oraciones,
explicando por qué el saco elegido sirve para el evento y cómo combina con lo que el usuario ya tiene.
Usá SOLO los datos provistos: no inventes características. No menciones precios, talles ni códigos
(se agregan aparte). Referite a las prendas propias como "tu ...". Si hay candidatos descartados,
mencioná en una oración por qué se descartaron."""


@lru_cache(maxsize=1)
def _llm() -> ChatGroq:
    return ChatGroq(model=GROQ_MODEL, temperature=0)


# ─────────────────────────── Funciones auxiliares ───────────────────────────

def _pesos(n: int) -> str:
    return "$" + f"{n:,}".replace(",", ".")


def _faltantes(prefs: dict) -> list[str]:
    return [campo for campo in REQUERIDOS if not prefs.get(campo)]


def _fusionar(prefs: dict, ext: Extraccion) -> dict:
    """Aplica lo que dijo el usuario sobre las preferencias ya conocidas."""
    nuevo = dict(prefs)
    for campo in ("evento", "temporada", "talle_saco", "presupuesto_max", "pedido"):
        valor = getattr(ext, campo)
        if valor is not None:
            nuevo[campo] = str(valor).strip() if campo == "talle_saco" else valor
    if ext.sin_tope_presupuesto:
        nuevo["presupuesto_max"] = None
    propias = list(nuevo.get("prendas_propias", []))
    conocidas = {p.lower() for p in propias}
    for prenda in ext.prendas_propias:
        if prenda.lower() not in conocidas:
            propias.append(prenda)
            conocidas.add(prenda.lower())
    nuevo["prendas_propias"] = propias
    return nuevo


def _motivo_descarte(e: dict, talle: str) -> str:
    if e["descartado"]:
        return "lo descartaste"
    if not e["temporada_ok"]:
        return f"es de {e['temporada']}"
    if not e["stock_ok"]:
        return f"agotado en talle {talle}"
    if not e["precio_ok"]:
        return f"cuesta {_pesos(e['precio'])}, más que tu presupuesto"
    return "no cumple"


def _mensaje(texto: str) -> dict:
    return {"messages": [AIMessage(content=texto)]}


# ─────────────────────────────── Nodos ───────────────────────────────

def extraer_preferencias(state: Estado) -> dict:
    """LLM: lee el último mensaje y actualiza las preferencias."""
    prefs = state.get("prefs", {})
    historial = "\n".join(
        f"{'Usuario' if isinstance(m, HumanMessage) else 'Asistente'}: {m.content}"
        for m in state["messages"][-5:]
    )
    prompt = PROMPT_EXTRACCION.format(prefs=json.dumps(prefs, ensure_ascii=False), historial=historial)
    ext = _llm().with_structured_output(Extraccion).invoke(prompt) or Extraccion()

    descartados = list(state.get("descartados", []))
    ultima = state.get("ultima_recomendacion")
    if ext.pide_alternativa and ultima and ultima not in descartados:
        descartados.append(ultima)  # "otra alternativa" = no volver a proponer la anterior
    return {"prefs": _fusionar(prefs, ext), "descartados": descartados}


def ruta_tras_extraer(state: Estado) -> str:
    """Decisión 1: ¿tenemos los datos mínimos?"""
    return "pedir_datos" if _faltantes(state["prefs"]) else "buscar_candidatos"


def pedir_datos(state: Estado) -> dict:
    faltan = ", ".join(REQUERIDOS[c] for c in _faltantes(state["prefs"]))
    return _mensaje(f"Para recomendarte algo necesito que me cuentes: {faltan}.")


def buscar_candidatos(state: Estado) -> dict:
    """RAG: busca fichas de sacos y guías de estilo relacionadas con el pedido."""
    prefs = state["prefs"]
    partes = ["saco", prefs["evento"]]
    if prefs["temporada"] in ("verano", "invierno"):
        partes.append(f"en {prefs['temporada']}")
    if prefs.get("pedido"):
        partes.append(prefs["pedido"])
    if prefs.get("prendas_propias"):
        partes.append("que combine con " + ", ".join(prefs["prendas_propias"]))
    consulta = " ".join(partes)

    candidatos = rag.buscar_productos(consulta, k=8, categoria="saco")
    guias = rag.buscar_guias(consulta, k=2)
    return {"trabajo": {"consulta": consulta, "candidatos": candidatos, "guias": guias}}


def ruta_tras_buscar(state: Estado) -> str:
    """Decisión 2: ¿el RAG encontró evidencia suficiente?"""
    return "verificar_disponibilidad" if state["trabajo"]["candidatos"] else "sin_evidencia"


def sin_evidencia(state: Estado) -> dict:
    return _mensaje(
        "No encontré en el catálogo sacos que se ajusten a ese pedido (evidencia insuficiente), "
        "así que prefiero no inventarte una recomendación. ¿Podés contarme con otras palabras qué "
        "buscás o más detalles del evento?"
    )


def verificar_disponibilidad(state: Estado) -> dict:
    """Base de datos: verifica talle, stock y precio de cada candidato."""
    prefs, trabajo = state["prefs"], state["trabajo"]
    talle, temporada, tope = prefs["talle_saco"], prefs["temporada"], prefs.get("presupuesto_max")
    descartados = set(state.get("descartados", []))

    evaluados = []
    for c in trabajo["candidatos"]:
        info = db.consultar_stock(c["id"], talle)  # fuente de verdad: SQLite
        evaluados.append({
            "id": c["id"], "nombre": c["nombre"], "score": c["score"], "texto": c["texto"],
            "temporada": c["temporada"],
            "unidades": info["unidades"], "precio": info["precio"],
            # La temporada se filtra con el dato estructurado: la búsqueda semántica la distingue mal.
            "temporada_ok": temporada == "cualquiera" or c["temporada"] == temporada,
            "stock_ok": info["unidades"] > 0,
            "precio_ok": tope is None or info["precio"] <= tope,
            "descartado": c["id"] in descartados,
        })
    viables = [
        e for e in evaluados
        if e["temporada_ok"] and e["stock_ok"] and e["precio_ok"] and not e["descartado"]
    ]
    return {"trabajo": {**trabajo, "evaluados": evaluados, "viables": viables}}


def ruta_tras_verificar(state: Estado) -> str:
    """Decisión 3: ¿hay al menos una opción que cumpla todas las restricciones?"""
    return "recomendar" if state["trabajo"]["viables"] else "diagnosticar"


def recomendar(state: Estado) -> dict:
    """LLM redacta la explicación; el código arma la ficha verificable."""
    prefs, trabajo = state["prefs"], state["trabajo"]
    talle, tope = prefs["talle_saco"], prefs.get("presupuesto_max")
    elegido = trabajo["viables"][0]  # el mejor puntaje semántico entre los viables

    # Candidatos mejor rankeados que se descartaron, y por qué.
    previos = [e for e in trabajo["evaluados"] if e["score"] > elegido["score"] and e["id"] != elegido["id"]]
    descartes = [f"{e['id']} ({_motivo_descarte(e, talle)})" for e in previos]

    propias = prefs.get("prendas_propias") or []
    datos = "\n".join([
        f"Evento: {prefs['evento']}",
        f"Época: {prefs['temporada']}",
        f"Prendas propias del usuario: {', '.join(propias) if propias else 'ninguna mencionada'}",
        f"Pedido: {prefs.get('pedido') or '(sin detalle)'}",
        f"Saco elegido: {elegido['texto']}",
        "Guías de estilo relevantes: " + (" | ".join(g["texto"] for g in trabajo["guias"]) or "ninguna"),
        "Candidatos mejor rankeados que se descartaron: "
        + ("; ".join(f"{e['nombre']}: {_motivo_descarte(e, talle)}" for e in previos) or "ninguno"),
    ])
    explicacion = _llm().invoke([SystemMessage(PROMPT_EXPLICACION), HumanMessage(datos)]).content.strip()

    fuentes = [f"ficha {elegido['id']}"] + [g["id"] for g in trabajo["guias"]]
    lineas = [
        f"**Prendas que ya tenés:** {', '.join(propias) if propias else '—'}",
        f"**Del catálogo:** {elegido['id']} · {elegido['nombre']} · talle {talle} · "
        f"{_pesos(elegido['precio'])} · {elegido['unidades']} u. en stock",
    ]
    if descartes:
        lineas.append("**Descartados (mejor puntaje que el elegido):** " + ", ".join(descartes[:3]))
    lineas.append("**Fuentes:** " + ", ".join(fuentes))

    salida = _mensaje(f"{explicacion}\n\n" + "\n".join(lineas))
    salida["ultima_recomendacion"] = elegido["id"]
    return salida


def diagnosticar(state: Estado) -> dict:
    """Ninguna combinación es viable: identifica qué restricción bloquea y pregunta qué cambio acepta."""
    prefs, trabajo = state["prefs"], state["trabajo"]
    talle, tope, temporada = prefs["talle_saco"], prefs.get("presupuesto_max"), prefs["temporada"]
    con_stock = [e for e in trabajo["evaluados"] if e["stock_ok"] and not e["descartado"]]

    por_precio = sorted((e for e in con_stock if e["temporada_ok"] and not e["precio_ok"]), key=lambda e: e["precio"])
    por_temporada = sorted((e for e in con_stock if not e["temporada_ok"] and e["precio_ok"]), key=lambda e: e["precio"])

    opciones = []
    if por_precio:
        e = por_precio[0]
        opciones.append(
            f"subir tu presupuesto a {_pesos(e['precio'])} o más (alcanza para {e['id']} · {e['nombre']})"
        )
    if por_temporada:
        e = por_temporada[0]
        opciones.append(
            f"aceptar un saco de {e['temporada']} (por ejemplo {e['id']} · {e['nombre']}, {_pesos(e['precio'])})"
        )

    if opciones:
        restricciones = f"talle {talle}, {temporada}" + (f" y hasta {_pesos(tope)}" if tope else "")
        texto = (
            f"No encontré ningún saco que cumpla todo a la vez ({restricciones}). "
            f"¿Qué cambio aceptarías: {' o '.join(opciones)}?"
        )
    else:
        texto = (
            f"Ningún saco que se ajuste a tu pedido tiene stock en talle {talle}. "
            "¿Aceptarías probar con otro talle o con un estilo distinto?"
        )
    return _mensaje(texto)


# ─────────────────────────────── Armado del grafo ───────────────────────────────

def construir_grafo():
    b = StateGraph(Estado)
    b.add_node("extraer_preferencias", extraer_preferencias)
    b.add_node("pedir_datos", pedir_datos)
    b.add_node("buscar_candidatos", buscar_candidatos)
    b.add_node("sin_evidencia", sin_evidencia)
    b.add_node("verificar_disponibilidad", verificar_disponibilidad)
    b.add_node("recomendar", recomendar)
    b.add_node("diagnosticar", diagnosticar)

    b.add_edge(START, "extraer_preferencias")
    b.add_conditional_edges("extraer_preferencias", ruta_tras_extraer,
                            {"pedir_datos": "pedir_datos", "buscar_candidatos": "buscar_candidatos"})
    b.add_conditional_edges("buscar_candidatos", ruta_tras_buscar,
                            {"sin_evidencia": "sin_evidencia", "verificar_disponibilidad": "verificar_disponibilidad"})
    b.add_conditional_edges("verificar_disponibilidad", ruta_tras_verificar,
                            {"recomendar": "recomendar", "diagnosticar": "diagnosticar"})
    for nodo_final in ("pedir_datos", "sin_evidencia", "recomendar", "diagnosticar"):
        b.add_edge(nodo_final, END)

    # El checkpointer guarda el estado de cada conversación (por thread_id).
    return b.compile(checkpointer=Checkpointer())


grafo = construir_grafo()


def conversar(texto: str, thread_id: str) -> dict:
    """Un turno de conversación. Devuelve la respuesta y el estado interno (para UI y evaluación)."""
    resultado = grafo.invoke(
        {"messages": [HumanMessage(texto)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return {
        "respuesta": resultado["messages"][-1].content,
        "prefs": resultado.get("prefs", {}),
        "trabajo": resultado.get("trabajo", {}),
        "descartados": resultado.get("descartados", []),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mermaid":
        print(grafo.get_graph().draw_mermaid())
        raise SystemExit

    escenarios = {
        "A) Caso típico + alternativa + cambio de preferencia": [
            "Hola! Voy a un casamiento de noche en verano. Uso talle 50 y tengo un pantalón negro. "
            "Busco un saco que combine.",
            "Mostrame otra alternativa",
            "Ahora mi presupuesto máximo es $150.000",
        ],
        "B) Dato faltante": [
            "Quiero un saco para una fiesta",
        ],
        "C) Restricción incumplida y respuesta del usuario": [
            "Voy a un casamiento de noche en verano, talle 56, tengo un pantalón negro. "
            "Mi presupuesto es de $120.000 como máximo.",
            "Dale, subo el presupuesto a $140.000",
        ],
        "D) Evidencia insuficiente": [
            "Necesito un disfraz de dinosaurio inflable para un cumpleaños infantil de verano, talle 50",
        ],
    }
    for nombre, mensajes in escenarios.items():
        print(f"\n{'=' * 70}\n{nombre}\n{'=' * 70}")
        hilo = f"demo-{nombre[0]}"
        for m in mensajes:
            print(f"\n👤 {m}")
            r = conversar(m, hilo)
            print(f"🤖 {r['respuesta']}")
            print(f"   [prefs: {r['prefs']}]")
