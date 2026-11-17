"""Base de datos SQLite: fuente de verdad de talle, stock y precio.

Uso (desde la raíz del proyecto):
    python -m src.db        # crea la base y corre una demo

crea las tablas y tiene dos funciones que después van a ser herramientas del agente:
consultar_stock(producto_id, talle) devuelve precio y unidades de un producto en un talle.
filtrar_productos(categoria, talle, precio_max, temporada)
devuelve lo que cumple todas las restricciones. Cuando da vacío,
se puede volver a correr aflojando una restricción por vez para descubrir cuál bloquea.
Eso es lo que necesitamos para el caso “sin combinación viable”.
"""


import json
import sqlite3
from contextlib import contextmanager

from src.config import DB_PATH, PRODUCTOS_JSON

SCHEMA = """
DROP TABLE IF EXISTS stock;
DROP TABLE IF EXISTS productos;

CREATE TABLE productos (
    id         TEXT PRIMARY KEY,
    nombre     TEXT NOT NULL,
    categoria  TEXT NOT NULL,      -- saco, camisa, ...
    color      TEXT,
    tela       TEXT,
    temporada  TEXT,               -- verano / invierno
    precio     INTEGER NOT NULL    -- en pesos
);

CREATE TABLE stock (
    producto_id TEXT NOT NULL REFERENCES productos(id),
    talle       TEXT NOT NULL,     -- "50", "M", ...
    unidades    INTEGER NOT NULL,
    PRIMARY KEY (producto_id, talle)
);
"""


@contextmanager
def conexion():
    """Abre una conexión, hace commit al terminar y la cierra siempre."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acceder a las columnas por nombre
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """(Re)crea la base desde data/productos.json. Se puede correr las veces que haga falta."""
    productos = json.loads(PRODUCTOS_JSON.read_text(encoding="utf-8"))
    with conexion() as conn:
        conn.executescript(SCHEMA)
        for p in productos:
            conn.execute(
                "INSERT INTO productos (id, nombre, categoria, color, tela, temporada, precio) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (p["id"], p["nombre"], p["categoria"], p["color"], p["tela"], p["temporada"], p["precio"]),
            )
            for talle, unidades in p["stock"].items():
                conn.execute(
                    "INSERT INTO stock (producto_id, talle, unidades) VALUES (?, ?, ?)",
                    (p["id"], talle, unidades),
                )


def consultar_stock(producto_id: str, talle: str) -> dict | None:
    """Precio y unidades de un producto en un talle.

    Devuelve None si el producto no existe. Si el talle no existe para ese
    producto, devuelve unidades = 0.
    """
    with conexion() as conn:
        fila = conn.execute(
            "SELECT p.id, p.nombre, p.precio, COALESCE(s.unidades, 0) AS unidades "
            "FROM productos p "
            "LEFT JOIN stock s ON s.producto_id = p.id AND s.talle = ? "
            "WHERE p.id = ?",
            (str(talle).upper(), producto_id),
        ).fetchone()
    if fila is None:
        return None
    return {
        "producto_id": fila["id"],
        "nombre": fila["nombre"],
        "talle": str(talle).upper(),
        "precio": fila["precio"],
        "unidades": fila["unidades"],
        "disponible": fila["unidades"] > 0,
    }


def filtrar_productos(
    categoria: str,
    talle: str,
    precio_max: int | None = None,
    temporada: str | None = None,
    solo_con_stock: bool = True,
) -> list[dict]:
    """Productos de una categoría que cumplen talle, presupuesto y temporada.

    Sirve para dos cosas: verificar candidatos y, cuando no hay resultados,
    averiguar qué restricción es la que bloquea (relajándolas de a una).
    """
    sql = (
        "SELECT p.id, p.nombre, p.color, p.temporada, p.precio, s.talle, s.unidades "
        "FROM productos p JOIN stock s ON s.producto_id = p.id "
        "WHERE p.categoria = ? AND s.talle = ?"
    )
    params: list = [categoria, str(talle).upper()]
    if solo_con_stock:
        sql += " AND s.unidades > 0"
    if precio_max is not None:
        sql += " AND p.precio <= ?"
        params.append(precio_max)
    if temporada is not None:
        sql += " AND p.temporada = ?"
        params.append(temporada)
    sql += " ORDER BY p.precio"

    with conexion() as conn:
        return [dict(f) for f in conn.execute(sql, params).fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"Base creada en {DB_PATH}\n")

    print("1) Stock de SAC-0417 en talle 50 (esperado: agotado):")
    print("  ", consultar_stock("SAC-0417", "50"))

    print("2) Stock de SAC-0388 en talle 50 (esperado: 3 u.):")
    print("  ", consultar_stock("SAC-0388", "50"))

    print("3) Sacos talle 56, hasta $120.000, de verano (esperado: ninguno):")
    print("  ", filtrar_productos("saco", "56", precio_max=120000, temporada="verano"))

    print("4) Lo mismo SIN tope de presupuesto (esperado: 2 sacos, desde $134.000):")
    for p in filtrar_productos("saco", "56", temporada="verano"):
        print("  ", p["id"], p["nombre"], p["precio"])
