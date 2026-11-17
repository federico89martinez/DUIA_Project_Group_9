# centraliza las rutas, la carga del .env y el modelo.
# Cambiá el valor por defecto de GROQ_MODEL por el que te funcionó en test_groq.py.

"""Configuración central: rutas, modelo y variables de entorno."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Raíz del proyecto (la carpeta que contiene src/ y data/)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # carga GROQ_API_KEY

DATA_DIR = BASE_DIR / "data"
PRODUCTOS_JSON = DATA_DIR / "productos.json"
GUIAS_JSON = DATA_DIR / "guias.json"
DB_PATH = DATA_DIR / "vestuario.db"

# Cambiá el valor por defecto por el modelo que te funcionó en test_groq.py
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
