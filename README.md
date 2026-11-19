# Asistente conversacional para elegir un vestuario

Trabajo práctico grupal · Módulo 6 · Diplomatura Universitaria en Inteligencia Artificial (Grupo 9).

- Martinez, Federico
- Jose, Guidi

Prueba de concepto en Python: un asistente que, para un evento, combina las preferencias y las
prendas propias del usuario con un catálogo, **verifica talle, stock y precio en una base de datos**
y devuelve una recomendación con fuentes. Está construido con LangChain, LangGraph, RAG y SQLite.
Los datos del catálogo son **simulados** (uso académico).

El análisis, las decisiones y los resultados de la validación están en [`INFORME.md`](INFORME.md).

## Requisitos

- Python 3.11 (probado con 3.11.7)
- Una clave de API de Groq (gratuita): https://console.groq.com
- Conexión a internet: llamadas a Groq y, **en la primera ejecución**, descarga del modelo de embeddings
  (varios cientos de MB, queda en caché)
- Servicios: solo Groq (externo). La base de datos es un archivo SQLite local, no requiere servidor.

## Instalación (desde una copia limpia)

```bash
git clone https://github.com/federico89martinez/DUIA_Project_Group_9.git  ->https
git clone git@github.com:federico89martinez/DUIA_Project_Group_9.git -> ssh

python3.11 -m venv .venv
source .venv/bin/activate            # en Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

cp .env.example .env                 # luego editá .env y pegá tu GROQ_API_KEY
```

La clave se configura **por fuera del repositorio**: `.env` está en `.gitignore`.
Para reproducir exactamente las versiones probadas: `python -m pip install -r requirements-lock.txt`.

> **Mac Intel:** torch no pasa de la versión 2.2.2, por eso `requirements.txt` fija
> `transformers<4.50` y `numpy<2`. Sin esos límites falla la carga del modelo de embeddings.

## Datos e índice

| Qué | Cómo |
|---|---|
| Datos de demostración | `data/productos.json` (8 sacos y 2 camisas) y `data/guias.json` (3 guías de estilo), simulados por el equipo |
| Base de datos (precio, talle, stock) | `python -m src.db` la crea en `data/vestuario.db` y corre 4 chequeos de ejemplo. La interfaz también la crea sola si no existe |
| Índice RAG | Se construye en memoria al iniciar (a partir de los mismos JSON). No hay paso aparte |

## Cómo probar el flujo completo

### Interfaz web (recomendado)

```bash
streamlit run src/app.py
```

Se abre en **http://localhost:8501**. La primera consulta tarda más (carga el modelo de embeddings).
La barra lateral tiene un botón por cada caso de prueba; a la derecha se ve qué hizo el sistema
(ruta, preferencias detectadas, consulta al RAG, candidatos verificados en la base).

**Caso exitoso** (botón "Caso típico"):

> Voy a un casamiento de noche en verano. Uso talle 50 y tengo un pantalón negro. Busco un saco que combine.

Esperado: recomienda un saco de verano con stock en talle 50, con ID, talle, precio y unidades
tomados de la base, y las fuentes citadas. Distingue "prendas que ya tenés" de lo "del catálogo".

**Caso problemático** (botón "Restricción incumplida"):

> Voy a un casamiento de noche en verano, talle 56, tengo un pantalón negro. Mi presupuesto es de $120.000 como máximo.

Esperado: no recomienda; identifica el presupuesto como la restricción que bloquea, ofrece opciones
con sus precios y pregunta qué cambio aceptaría. Si luego se responde
`Dale, subo el presupuesto a $140.000`, recomienda un saco de talle 56 dentro del nuevo tope
(el sistema recuerda el talle y las prendas propias).

Otros casos disponibles con botón: **dato faltante** (`Quiero un saco para una fiesta`) y
**evidencia insuficiente** (un disfraz de dinosaurio).

### Sin interfaz

```bash
python -m src.graph            # corre 4 conversaciones de ejemplo en la consola
python -m src.graph mermaid    # imprime el diagrama del grafo (formato Mermaid)
python -m src.rag              # demo del RAG: puntajes de similitud por consulta
python -m src.tools            # prueba qué herramienta elige el LLM para cada pedido
```

## Repetir la validación

```bash
python -m src.db                  # si todavía no existe la base
python -m evaluacion.run_eval     # corre los 5 casos
python -m evaluacion.run_eval C4  # o solo algunos
```

Hace unas 7 llamadas a Groq. Cada caso muestra PASS/FAIL en la consola y se escribe el detalle en
`evaluacion/resultados.md` y `evaluacion/resultados.json`. Los casos están en `evaluacion/casos.json`.
Se espera que **C5 falle**: documenta una limitación conocida (ver `INFORME.md`).

## Estructura

```
├── README.md · INFORME.md
├── requirements.txt · requirements-lock.txt · .env.example · .gitignore
├── data/
│   ├── productos.json        # catálogo simulado (precio, stock por talle, descripción)
│   └── guias.json            # guías de estilo
├── src/
│   ├── config.py             # rutas, modelo, carga del .env
│   ├── db.py                 # SQLite: stock, talle y precio
│   ├── rag.py                # embeddings, índices y búsqueda con umbral de evidencia
│   ├── tools.py              # las funciones expuestas como tools de LangChain
│   ├── graph.py              # grafo de LangGraph: el flujo del asistente
│   └── app.py                # interfaz Streamlit
└── evaluacion/
    ├── casos.json            # casos: entrada, esperado
    ├── run_eval.py           # ejecuta los casos y valida las salidas
    └── resultados.md/.json   # salida de la última ejecución
```

## Problemas frecuentes

- **`ModuleNotFoundError: No module named 'src'`**: ejecutá siempre desde la raíz del proyecto y con
  `python -m ...` (por ejemplo `python -m src.db`), no con `python src/db.py`.
- **Error de la API de Groq (404 / modelo no existe)**: el modelo por defecto es `openai/gpt-oss-120b`.
  Si tu cuenta no lo tiene, definí otro en `.env` con `GROQ_MODEL=...`.
- **Límite de uso de la API**: la capa gratuita tiene límites; esperá un momento y reintentá.
