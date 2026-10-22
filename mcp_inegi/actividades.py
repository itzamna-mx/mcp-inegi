"""Catálogo SCIAN: traduce "tortillerías" o "farmacias" al código de actividad del DENUE."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

from .areas import normalizar

NIVELES = {2: "sector", 3: "subsector", 4: "rama", 5: "subrama", 6: "clase"}

# Palabras que la gente agrega y no ayudan a distinguir la actividad.
_VACIAS = {
    "de", "la", "el", "los", "las", "y", "o", "en", "con", "sin", "para", "por", "a", "al",
    "del", "un", "una", "unos", "unas", "e", "u", "tienda", "tiendas", "negocio", "negocios",
    "local", "locales", "establecimiento", "establecimientos", "lugar", "lugares",
}


# Cómo lo dice la gente -> cómo lo dice el SCIAN.
_SINONIMOS = {
    "gimnasio": "centros acondicionamiento fisico",
    "gimnasios": "centros acondicionamiento fisico",
    "gym": "centros acondicionamiento fisico",
    "dentista": "consultorios dentales",
    "dentistas": "consultorios dentales",
    "estetica": "salones belleza",
    "esteticas": "salones belleza",
    "peluqueria": "salones belleza peluquerias",
    "peluquerias": "salones belleza peluquerias",
    "barberia": "salones belleza peluquerias",
    "barberias": "salones belleza peluquerias",
    "doctor": "consultorios medicina general",
    "medico": "consultorios medicina general",
    "medicos": "consultorios medicina general",
    "veterinaria": "servicios veterinarios",
    "veterinarias": "servicios veterinarios",
    "veterinario": "servicios veterinarios",
    "oxxo": "comercio menor minisupers",
    "conveniencia": "comercio menor minisupers",
    "mayoreo": "mayor",
    "menudeo": "menor",
    "venta": "comercio",
    "ventas": "comercio",
    "super": "supermercados",
    "supermercado": "supermercados",
    "tiendita": "abarrotes",
    "tienditas": "abarrotes",
    "taqueria": "tacos",
    "taquerias": "tacos",
    "fonda": "comida corrida",
    "fondas": "comida corrida",
    "gasolinera": "gasolina",
    "gasolineras": "gasolina",
    "lavanderia": "lavanderias",
    "cafe": "cafeterias",
    "bar": "centros nocturnos bares",
    "bares": "centros nocturnos bares",
}

# Manufactura (31-33) y mayoreo (43): en un empate casi siempre se busca la tienda o el servicio.
_POCO_PROBABLES = ("31", "32", "33", "43")


def _sinonimo(palabra: str) -> str:
    """Sinónimo de una palabra o de su singular ("oxxos" -> "oxxo", "bares" -> "bar")."""
    for forma in (palabra, palabra[:-1] if palabra.endswith("s") else None,
                  palabra[:-2] if palabra.endswith("es") else None):
        if forma and forma in _SINONIMOS:
            return _SINONIMOS[forma]
    return palabra


def _expandir(texto: str) -> str:
    return " ".join(_sinonimo(w) for w in _palabras(texto))


# El SCIAN usa "elaboración" y "fabricación" para lo mismo.
_RAICES_EQUIVALENTES = {"elabor": "fabric"}


def _raiz(palabra: str) -> str:
    """Raíz burda: "tortillería", "tortillas" y "tortillero" comparten "tortil"."""
    raiz = palabra[:6] if len(palabra) > 6 else palabra.rstrip("s") or palabra
    return _RAICES_EQUIVALENTES.get(raiz, raiz)


def _palabras(texto: str) -> list[str]:
    return re.findall(r"\w+", normalizar(texto))


def _raices(texto: str) -> set[str]:
    """Raíces significativas; lo que sigue a "sin" se descarta ("Farmacias sin minisúper")."""
    palabras = _palabras(texto)
    return {
        _raiz(w)
        for i, w in enumerate(palabras)
        if w not in _VACIAS and (i == 0 or palabras[i - 1] != "sin")
    }


@lru_cache(maxsize=1)
def catalogo() -> dict[str, dict[str, str]]:
    """{código SCIAN: {"n": título, "p": palabras de productos}}, de scripts/generar_scian.py."""
    texto = files("mcp_inegi").joinpath("data/scian.json").read_text(encoding="utf-8")
    return json.loads(texto)


@lru_cache(maxsize=1)
def _indice() -> list[tuple[str, str, set[str], set[str]]]:
    return [
        (codigo, info["n"], _raices(info["n"]), {_raiz(w) for w in info["p"].split()})
        for codigo, info in catalogo().items()
    ]


def nombre_actividad(codigo: str) -> str | None:
    info = catalogo().get(codigo)
    return info["n"] if info else None


def ficha_actividad(codigo: str) -> dict[str, str | None]:
    return {
        "codigo": codigo,
        "nivel": NIVELES.get(len(codigo)),
        "nombre": nombre_actividad(codigo),
    }


def buscar_actividades(texto: str, limite: int = 10) -> list[dict[str, str | None]]:
    """Códigos SCIAN que mejor coinciden con una descripción en lenguaje natural.

    Pesa más que la palabra esté en el título de la actividad que en su índice de productos,
    y más aún que el título empiece con ella ("Farmacias sin minisúper" para "farmacia").
    Entre empates gana la clase de 6 dígitos, que es lo que el DENUE asigna a cada negocio, y
    pierden manufactura y mayoreo. Antes se traducen palabras coloquiales ("gimnasio", "oxxo").
    """
    texto = _expandir(texto)
    consulta = _raices(texto)
    if not consulta:
        return []
    primera = _raiz(texto.split()[0]) if texto else ""

    puntuados = []
    for codigo, titulo, en_titulo, en_productos in _indice():
        presentes = consulta & (en_titulo | en_productos)
        if len(presentes) < len(consulta):
            continue
        puntaje = 3 * len(consulta & en_titulo) + len(consulta & en_productos)
        if _raiz(_palabras(titulo)[0]) == primera:
            puntaje += 2
        if codigo.startswith(_POCO_PROBABLES):
            puntaje -= 1
        puntuados.append((-puntaje, -len(codigo), len(titulo), codigo))

    puntuados.sort()
    return [ficha_actividad(c) for *_, c in puntuados[:limite]]
