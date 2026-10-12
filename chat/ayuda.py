"""Búsqueda en la base de conocimiento (carpeta `conocimiento/`).

Versión 1: búsqueda por palabras sobre secciones de Markdown, sin embeddings.
Es suficiente para unas decenas de páginas; cuando crezca, sustituir por
embeddings (ver docs/PLAN.md › Fase 1).
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings

CARPETA = Path(settings.BASE_DIR) / "conocimiento"
VACIAS = set(
    "a al algo como con cual cuando de del donde el ella en es esa ese eso esta este "
    "hay la las lo los mas me mi no o para pero por que se si sin sobre su sus te "
    "tu un una uno unos y ya yo hacer hago puedo puede quiero".split()
)


def _norm(texto):
    texto = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [p for p in re.findall(r"[a-z0-9]+", texto) if p not in VACIAS and len(p) > 1]


@lru_cache(maxsize=1)
def secciones():
    salida = []
    for fichero in sorted(CARPETA.glob("*.md")):
        if fichero.name == "README.md":
            continue
        actual, lineas = fichero.stem, []
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            if re.match(r"^#{1,3} ", linea):
                if lineas:
                    salida.append((fichero.name, actual, "\n".join(lineas).strip()))
                actual, lineas = linea.lstrip("# ").strip(), []
            else:
                lineas.append(linea)
        if lineas:
            salida.append((fichero.name, actual, "\n".join(lineas).strip()))
    return [s for s in salida if s[2]]


def buscar(consulta, maximo=4):
    terminos = set(_norm(consulta))
    if not terminos:
        return []
    puntuadas = []
    for fichero, titulo, texto in secciones():
        palabras_titulo = set(_norm(titulo))
        palabras = _norm(texto)
        cuenta = sum(1 for p in palabras if p in terminos)
        puntos = cuenta + 3 * len(terminos & palabras_titulo)
        if puntos:
            puntuadas.append((puntos, fichero, titulo, texto))
    puntuadas.sort(key=lambda x: -x[0])
    return [
        {"fuente": f"{f} › {t}", "texto": tx[:2500]}
        for _, f, t, tx in puntuadas[:maximo]
    ]
