"""Herramientas (tools) que el LLM puede llamar.

Una tool es una función normal de Python + una descripción. El LLM NO ejecuta
nada: lee el nombre, la descripción y los argumentos de cada tool y, según lo
que pide el usuario, responde "quiero llamar a X con estos argumentos". Después
nuestro código la ejecuta y le devuelve el resultado.

Por eso las descripciones (docstrings) son parte de la "interfaz" con el modelo:
si están mal escritas, el modelo elige mal.

Uso (desde la raíz del proyecto):
    python -m src.tools      # prueba qué tool elige el modelo para cada pedido
"""
from typing import Literal

from langchain_core.tools import tool

from src import db, rag


@tool(parse_docstring=True)
def buscar_productos(consulta: str, categoria: Literal["saco", "camisa"] | None = None) -> dict:
    """Busca productos del catálogo por significado (búsqueda semántica).

    Usala para encontrar candidatos para una ocasión, estilo o color. NO informa
    talle, stock ni precio: para eso usá consultar_stock.

    Args:
        consulta: descripción de lo que se busca, por ejemplo "saco azul para casamiento de noche en verano".
        categoria: opcional, limita la búsqueda a "saco" o "camisa".
    """
    resultados = rag.buscar_productos(consulta, k=4, categoria=categoria)
    if not resultados:
        return {
            "resultados": [],
            "mensaje": "No se encontró evidencia suficiente en el catálogo para esta consulta.",
        }
    campos = ("id", "nombre", "categoria", "color", "temporada", "score", "texto")
    return {"resultados": [{c: r[c] for c in campos} for r in resultados]}


@tool(parse_docstring=True)
def buscar_guias_estilo(consulta: str) -> dict:
    """Busca guías de estilo sobre qué ropa es adecuada para una ocasión o combinación.

    Usala cuando haga falta saber qué se usa en un tipo de evento o qué colores
    combinan, antes o junto con la búsqueda de productos.

    Args:
        consulta: la pregunta de estilo, por ejemplo "qué se usa en un casamiento de noche".
    """
    resultados = rag.buscar_guias(consulta, k=2)
    if not resultados:
        return {"resultados": [], "mensaje": "No se encontró ninguna guía de estilo relevante."}
    return {"resultados": resultados}


@tool(parse_docstring=True)
def consultar_stock(producto_id: str, talle: str | int) -> dict:
    """Consulta en la base de datos el precio y las unidades disponibles de UN producto en UN talle.

    Usala siempre antes de recomendar un producto concreto, para verificar que
    haya stock en el talle del usuario y conocer el precio real.

    Args:
        producto_id: identificador del producto, por ejemplo "SAC-0417".
        talle: talle a verificar, por ejemplo "50" para sacos o "M" para camisas.
    """
    resultado = db.consultar_stock(producto_id, str(talle))
    if resultado is None:
        return {"error": f"No existe el producto {producto_id}."}
    return resultado


@tool(parse_docstring=True)
def filtrar_disponibles(
    categoria: Literal["saco", "camisa"],
    talle: str | int,
    precio_max: int | None = None,
    temporada: Literal["verano", "invierno"] | None = None,
) -> dict:
    """Lista los productos con stock que cumplen TODAS las restricciones dadas.

    Usala para ver qué hay realmente disponible en un talle, presupuesto y
    temporada, o para averiguar qué restricción bloquea cuando no hay nada
    (volviéndola a llamar sin el presupuesto o sin la temporada).

    Args:
        categoria: "saco" o "camisa".
        talle: talle del usuario, por ejemplo "50" o "M".
        precio_max: presupuesto máximo en pesos para esta prenda (opcional).
        temporada: "verano" o "invierno" (opcional).
    """
    resultados = db.filtrar_productos(categoria, str(talle), precio_max=precio_max, temporada=temporada)
    if not resultados:
        return {"resultados": [], "mensaje": "Ningún producto cumple todas las restricciones."}
    return {"resultados": resultados}


TOOLS = [buscar_productos, buscar_guias_estilo, consultar_stock, filtrar_disponibles]


if __name__ == "__main__":
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    from src.config import GROQ_MODEL

    print("Tools disponibles y los argumentos que ve el modelo:")
    for t in TOOLS:
        print(f"  - {t.name}: {list(t.args.keys())}")

    llm = ChatGroq(model=GROQ_MODEL, temperature=0).bind_tools(TOOLS)
    sistema = SystemMessage(
        "Sos un asistente de una tienda de ropa. Para datos del catálogo, stock o "
        "precios usá siempre las herramientas; no inventes información."
    )
    mapa = {t.name: t for t in TOOLS}

    pedidos = [
        "Busco un saco para un casamiento de noche en verano",
        "¿Hay stock del SAC-0417 en talle 50?",
        "¿Qué se usa en un casamiento de noche?",
        "Necesito un saco talle 56 de verano hasta $120.000",
        "Contame un chiste corto",
    ]
    for pedido in pedidos:
        print(f"\n>>> {pedido}")
        respuesta = llm.invoke([sistema, HumanMessage(pedido)])
        if not respuesta.tool_calls:
            print("  (sin tools) El modelo respondió directo:", respuesta.content[:120])
            continue
        for llamada in respuesta.tool_calls:
            print(f"  El modelo eligió: {llamada['name']}({llamada['args']})")
            resultado = mapa[llamada["name"]].invoke(llamada["args"])
            print(f"  Resultado: {str(resultado)[:300]}")
