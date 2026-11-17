"""RAG: busca fichas de producto y guías de estilo por similitud semántica.

Qué hace (y qué NO hace):
  - Convierte cada ficha/guía en un vector (embedding) y busca las más
    parecidas a la consulta del usuario.
  - NO sabe de stock, talle ni precio: eso se verifica después en la base (db.py).

Uso (desde la raíz del proyecto):
    python -m src.rag        # demo con varias consultas y sus puntajes
"""
import json
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings

from src.config import GUIAS_JSON, PRODUCTOS_JSON

# Modelo de embeddings local y multilingüe (entiende español). La primera vez
# se descarga de internet (varios cientos de MB) y queda en caché.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Puntaje mínimo (similitud coseno) para considerar que hay evidencia.
# Por debajo de este valor, el resultado se descarta.
# OJO: estos valores son una primera estimación. Hay que calibrarlos mirando
# los puntajes que imprime la demo (ver más abajo).
SCORE_MIN_PRODUCTOS = 0.45
SCORE_MIN_GUIAS = 0.33


@lru_cache(maxsize=1)
def _embeddings() -> HuggingFaceEmbeddings:
    # normalize_embeddings=True -> los vectores quedan de largo 1, y el puntaje
    # es directamente la similitud coseno (entre -1 y 1, más alto = más parecido).
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache(maxsize=1)
def _indices() -> tuple[InMemoryVectorStore, InMemoryVectorStore]:
    """Construye los dos índices una sola vez y los reutiliza."""
    productos = json.loads(PRODUCTOS_JSON.read_text(encoding="utf-8"))
    guias = json.loads(GUIAS_JSON.read_text(encoding="utf-8"))

    # Lo que se indexa es SOLO texto descriptivo. Precio y stock quedan afuera
    # a propósito: su fuente de verdad es la base de datos.
    docs_productos = [
        Document(
            page_content=f"{p['nombre']}. {p['descripcion']}",
            metadata={
                "id": p["id"],
                "nombre": p["nombre"],
                "categoria": p["categoria"],
                "color": p["color"],
                "temporada": p["temporada"],
            },
        )
        for p in productos
    ]
    docs_guias = [Document(page_content=g["texto"], metadata={"id": g["id"]}) for g in guias]

    emb = _embeddings()
    idx_productos = InMemoryVectorStore(emb)
    idx_productos.add_documents(docs_productos)
    idx_guias = InMemoryVectorStore(emb)
    idx_guias.add_documents(docs_guias)
    return idx_productos, idx_guias


def buscar_productos(
    consulta: str,
    k: int = 4,
    categoria: str | None = None,
    score_min: float = SCORE_MIN_PRODUCTOS,
) -> list[dict]:
    """Fichas de producto más parecidas a la consulta, de mejor a peor.

    Devuelve [] si ninguna supera score_min -> "evidencia insuficiente".
    """
    idx_productos, _ = _indices()
    # Traemos todo (el corpus es chico) y filtramos acá. En un corpus grande se
    # filtraría dentro del vector store.
    resultados = idx_productos.similarity_search_with_score(consulta, k=100)

    salida = []
    for doc, score in resultados:
        if categoria and doc.metadata["categoria"] != categoria:
            continue
        if score < score_min:
            continue
        salida.append({**doc.metadata, "score": round(float(score), 3), "texto": doc.page_content})
    salida.sort(key=lambda r: r["score"], reverse=True)
    return salida[:k]


def buscar_guias(
    consulta: str,
    k: int = 2,
    score_min: float = SCORE_MIN_GUIAS,
) -> list[dict]:
    """Guías de estilo más parecidas a la consulta. Devuelve [] si no hay evidencia."""
    _, idx_guias = _indices()
    resultados = idx_guias.similarity_search_with_score(consulta, k=100)

    salida = [
        {"id": doc.metadata["id"], "score": round(float(score), 3), "texto": doc.page_content}
        for doc, score in resultados
        if score >= score_min
    ]
    salida.sort(key=lambda r: r["score"], reverse=True)
    return salida[:k]


if __name__ == "__main__":
    # Demo: mostramos TODOS los puntajes (score_min muy bajo) y marcamos con ✓
    # los que pasarían el umbral. Sirve para calibrar SCORE_MIN_*.
    consultas = [
        ("saco azul para un casamiento de noche en verano", "saco"),
        ("algo abrigado para una fiesta en invierno", "saco"),
        ("saco que combine con pantalón negro", "saco"),
        ("camisa blanca formal", "camisa"),
        ("zapatillas de running", None),          # fuera del catálogo
        ("receta de milanesa con puré", None),    # nada que ver
    ]
    for consulta, categoria in consultas:
        print(f"\nConsulta: {consulta!r}  (categoría: {categoria})")
        print("  Productos:")
        for r in buscar_productos(consulta, k=4, categoria=categoria, score_min=-1):
            marca = "✓" if r["score"] >= SCORE_MIN_PRODUCTOS else "✗"
            print(f"    {marca} {r['score']:.3f}  {r['id']}  {r['nombre']}")
        print("  Guías:")
        for r in buscar_guias(consulta, k=3, score_min=-1):
            marca = "✓" if r["score"] >= SCORE_MIN_GUIAS else "✗"
            print(f"    {marca} {r['score']:.3f}  {r['id']}  {r['texto'][:60]}...")
