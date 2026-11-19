"""Evaluación del agente: corre los casos de evaluacion/casos.json y valida cada salida.

Uso (desde la raíz del proyecto):
    python -m evaluacion.run_eval            # todos los casos
    python -m evaluacion.run_eval C4 C6      # solo algunos

Para cada caso registra: entrada, resultado esperado, salida observada y resultado de la
validación. Escribe evaluacion/resultados.json y evaluacion/resultados.md.

Las verificaciones son AUTOMÁTICAS y leen el texto de la respuesta (lo que ve el usuario),
comparándolo contra la base de datos (db.py) y las guías (data/guias.json).
"""
import json
import re
import sys
from pathlib import Path

from src import db
from src.config import GUIAS_JSON
from src.graph import conversar

CARPETA = Path(__file__).resolve().parent

DIMENSIONES = {
    "accion": "Acción adecuada",
    "evidencia": "Evidencia pertinente",
    "fundamento": "Respuesta apoyada en la evidencia",
    "extraccion": "Extracción del pedido",
}

TARJETA = re.compile(r"\*\*Del catálogo:\*\* (\S+) · (.+?) · talle (\S+) · \$([\d\.]+) · (\d+) u\.")
PRECIO_DE_ID = re.compile(r"((?:SAC|CAM)-\d{4}) · [^$]*?\$([\d\.]+)")


def a_int(texto: str) -> int:
    return int(texto.replace(".", ""))


def producto_bd(pid: str) -> dict | None:
    with db.conexion() as conn:
        fila = conn.execute(
            "SELECT id, nombre, color, temporada, precio FROM productos WHERE id = ?", (pid,)
        ).fetchone()
    return dict(fila) if fila else None


def verificar(caso: dict, resultados: list[dict]) -> list[dict]:
    """Aplica las verificaciones sobre el ÚLTIMO turno del caso."""
    esp = caso["esperado"]
    r = resultados[-1]
    texto = r["respuesta"]
    checks: list[dict] = []

    def chk(dimension: str, nombre: str, ok: bool, detalle: str = "") -> None:
        checks.append({"dimension": dimension, "check": nombre, "ok": bool(ok), "detalle": detalle})

    # ── Comunes a todos los casos ──
    chk("accion", "eligió la ruta esperada", r["ruta"] == esp["ruta"],
        f"esperada={esp['ruta']} observada={r['ruta']}")
    for campo, valor in esp.get("prefs", {}).items():
        real = r["prefs"].get(campo)
        chk("extraccion", f"preferencia {campo}", str(real) == str(valor), f"esperado={valor} observado={real}")
    if "evento_contiene" in esp:
        evento = (r["prefs"].get("evento") or "").lower()
        chk("extraccion", "el evento conserva el detalle", esp["evento_contiene"] in evento, f"evento={evento!r}")
    if "guia_recuperada" in esp:
        ids = [g["id"] for g in r["trabajo"].get("guias", [])]
        chk("evidencia", f"el RAG recuperó {esp['guia_recuperada']}", esp["guia_recuperada"] in ids,
            f"recuperadas={ids}")

    # ── Según la ruta esperada ──
    ruta = esp["ruta"]
    if ruta == "recomendar":
        _checks_recomendar(esp, resultados, texto, chk)
    elif ruta == "diagnosticar":
        _checks_diagnosticar(esp, texto, chk)
    elif ruta == "pedir_datos":
        chk("fundamento", "no recomienda nada", "**Del catálogo:**" not in texto)
        faltan = esp.get("palabras", [])
        chk("accion", "pide los datos que faltan", all(p in texto.lower() for p in faltan), f"debía nombrar={faltan}")
    elif ruta == "sin_evidencia":
        chk("fundamento", "no inventa productos", not re.search(r"(SAC|CAM)-\d{4}", texto))
        chk("evidencia", "el RAG no encontró candidatos sobre el umbral", not r["trabajo"].get("candidatos"),
            f"candidatos={len(r['trabajo'].get('candidatos', []))}")
    return checks


def _checks_recomendar(esp: dict, resultados: list[dict], texto: str, chk) -> None:
    m = TARJETA.search(texto)
    chk("fundamento", "la respuesta incluye la ficha con ID, talle, precio y stock", m is not None)
    if not m:
        return
    pid, talle, precio, unidades = m.group(1), m.group(3), a_int(m.group(4)), int(m.group(5))
    prod = producto_bd(pid)
    chk("fundamento", "el producto existe en la base", prod is not None, pid)
    if prod is None:
        return
    stock = db.consultar_stock(pid, talle)
    chk("fundamento", "el talle es el del usuario", talle == esp["talle"], f"ficha={talle} esperado={esp['talle']}")
    chk("fundamento", "el precio coincide con la base", precio == prod["precio"],
        f"ficha={precio} base={prod['precio']}")
    chk("fundamento", "el stock coincide con la base y es mayor que 0",
        unidades == stock["unidades"] and unidades > 0, f"ficha={unidades} base={stock['unidades']}")
    if esp.get("presupuesto_max"):
        chk("fundamento", "respeta el presupuesto", prod["precio"] <= esp["presupuesto_max"],
            f"precio={prod['precio']} tope={esp['presupuesto_max']}")
    if esp.get("temporada"):
        chk("fundamento", "la temporada es la pedida", prod["temporada"] == esp["temporada"],
            f"producto={prod['temporada']} pedida={esp['temporada']}")
    if esp.get("colores_excluidos"):
        chk("evidencia", "el color es adecuado para el evento", prod["color"] not in esp["colores_excluidos"],
            f"{pid} es {prod['color']}; desaconsejados={esp['colores_excluidos']}")
    if esp.get("distinto_del_turno_anterior"):
        previo = TARJETA.search(resultados[-2]["respuesta"])
        chk("accion", "no repite la recomendación anterior", bool(previo) and previo.group(1) != pid,
            f"anterior={previo.group(1) if previo else None} actual={pid}")

    guias_validas = {g["id"] for g in json.loads(GUIAS_JSON.read_text(encoding="utf-8"))}
    fuentes = re.search(r"\*\*Fuentes:\*\* (.+)", texto)
    citadas = [x.strip() for x in fuentes.group(1).split(",")] if fuentes else []
    ok = f"ficha {pid}" in citadas and all(c.startswith("ficha ") or c in guias_validas for c in citadas)
    chk("fundamento", "cita su ficha y solo guías que existen", ok, f"fuentes={citadas}")


def _checks_diagnosticar(esp: dict, texto: str, chk) -> None:
    chk("fundamento", "no presenta una recomendación", "**Del catálogo:**" not in texto)
    chk("accion", "pide una aclaración al usuario", "?" in texto)
    palabras = esp.get("palabras", [])
    chk("accion", "identifica la restricción", all(p in texto.lower() for p in palabras), f"debía nombrar={palabras}")
    pares = PRECIO_DE_ID.findall(texto)
    if pares:
        bien = all((p := producto_bd(i)) is not None and p["precio"] == a_int(pr) for i, pr in pares)
        chk("fundamento", "los precios citados coinciden con la base", bien, str(pares))


def main(argv: list[str]) -> None:
    casos = json.loads((CARPETA / "casos.json").read_text(encoding="utf-8"))
    if argv:
        casos = [c for c in casos if c["id"] in argv]

    informe = []
    for caso in casos:
        print(f"\n▶ {caso['id']} · {caso['nombre']}")
        resultados: list[dict] = []
        try:
            for mensaje in caso["mensajes"]:
                print(f"   👤 {mensaje}")
                resultados.append(conversar(mensaje, f"eval-{caso['id']}"))
            checks = verificar(caso, resultados)
        except Exception as error:  # p. ej. límite de uso de la API
            checks = [{"dimension": "accion", "check": "ejecución sin errores", "ok": False, "detalle": str(error)}]
        aprobado = all(c["ok"] for c in checks)
        print("   " + ("✅ PASS" if aprobado else "❌ FAIL"))
        for c in checks:
            if not c["ok"]:
                print(f"      ✗ {c['check']} ({c['detalle']})")
        informe.append({
            "id": caso["id"], "nombre": caso["nombre"], "entrada": caso["mensajes"],
            "esperado": caso["descripcion_esperado"], "nota": caso.get("nota", ""),
            "observado": resultados[-1]["respuesta"] if resultados else "",
            "ruta_observada": resultados[-1]["ruta"] if resultados else None,
            "checks": checks, "resultado": "PASS" if aprobado else "FAIL",
        })

    total, pasan = len(informe), sum(1 for i in informe if i["resultado"] == "PASS")
    print(f"\n{'=' * 50}\nResultado: {pasan}/{total} casos aprobados")
    (CARPETA / "resultados.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    (CARPETA / "resultados.md").write_text(_a_markdown(informe), encoding="utf-8")
    print("Guardado en evaluacion/resultados.json y evaluacion/resultados.md")


def _a_markdown(informe: list[dict]) -> str:
    L = ["# Resultados de la evaluación", "",
         "| Caso | Nombre | Resultado |", "|---|---|---|"]
    for i in informe:
        L.append(f"| {i['id']} | {i['nombre']} | {'✅ PASS' if i['resultado'] == 'PASS' else '❌ FAIL'} |")

    L += ["", "## Verificaciones por dimensión", "", "| Dimensión | Aprobadas |", "|---|---|"]
    for clave, etiqueta in DIMENSIONES.items():
        cs = [c for i in informe for c in i["checks"] if c["dimension"] == clave]
        if cs:
            L.append(f"| {etiqueta} | {sum(c['ok'] for c in cs)}/{len(cs)} |")

    for i in informe:
        L += ["", f"## {i['id']} · {i['nombre']} — {i['resultado']}", "", "**Entrada:**"]
        L += [f"{n}. {m}" for n, m in enumerate(i["entrada"], 1)]
        L += ["", f"**Esperado:** {i['esperado']}"]
        if i["nota"]:
            L += ["", f"**Nota:** {i['nota']}"]
        L += ["", f"**Salida observada** (ruta: `{i['ruta_observada']}`):", "", "```", i["observado"], "```", "",
              "| Dimensión | Verificación | Resultado | Detalle |", "|---|---|---|---|"]
        for c in i["checks"]:
            L.append(f"| {DIMENSIONES[c['dimension']]} | {c['check']} | {'✅' if c['ok'] else '❌'} | {c['detalle']} |")
        L += ["", "**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main(sys.argv[1:])
