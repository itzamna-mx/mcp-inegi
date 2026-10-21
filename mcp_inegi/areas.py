"""Resolución de áreas geográficas: país, estados y municipios por nombre o por clave."""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from importlib.resources import files

from .constants import AREA_NACIONAL, ESTADOS

# Nombres comunes que no coinciden con el nombre oficial del estado.
_ALIAS_ESTADOS = {
    "nacional": "00",
    "mexico": "00",
    "republica mexicana": "00",
    "estados unidos mexicanos": "00",
    "cdmx": "09",
    "df": "09",
    "distrito federal": "09",
    "edomex": "15",
    "estado de mexico": "15",
    "coahuila": "05",
    "michoacan": "16",
    "veracruz": "30",
    "queretaro de arteaga": "22",
    "nl": "19",
    "bc": "02",
    "bcs": "03",
}

# Prefijos que la gente antepone al nombre del municipio.
_PREFIJOS = ("municipio de ", "municipio ", "alcaldia de ", "alcaldia ", "delegacion ")


class AreaAmbiguaError(ValueError):
    """El nombre coincide con municipios de varios estados."""

    def __init__(self, texto: str, candidatos: list[dict[str, str]]):
        self.candidatos = candidatos
        opciones = "; ".join(f"{c['nombre']}, {c['estado']} ({c['clave']})" for c in candidatos[:10])
        extra = f" y {len(candidatos) - 10} más" if len(candidatos) > 10 else ""
        super().__init__(
            f"'{texto}' coincide con {len(candidatos)} municipios: {opciones}{extra}. "
            "Indica el estado ('Benito Juárez, CDMX') o usa la clave de 5 dígitos."
        )


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios simples."""
    sin_acentos = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
    return " ".join(sin_acentos.lower().replace(".", " ").split())


_POR_NOMBRE = {normalizar(nombre): clave for clave, nombre in ESTADOS.items()}
_POR_NOMBRE.update(_ALIAS_ESTADOS)


@lru_cache(maxsize=1)
def municipios() -> dict[str, str]:
    """Catálogo {clave de 5 dígitos: nombre oficial}, generado por scripts/generar_municipios.py."""
    texto = files("mcp_inegi").joinpath("data/municipios.json").read_text(encoding="utf-8")
    return json.loads(texto)


@lru_cache(maxsize=1)
def _municipios_normalizados() -> list[tuple[str, str]]:
    return [(clave, normalizar(nombre)) for clave, nombre in municipios().items()]


def _estado(texto: str, *, en_contexto: bool = False) -> str | None:
    """Clave de 2 dígitos de un estado por nombre o número, o None.

    Con `en_contexto` ("Naucalpan, México") "México" es el estado, no el país.
    """
    t = normalizar(texto)
    if t.isdigit() and len(t) <= 2 and t.zfill(2) in ESTADOS:
        return t.zfill(2)
    if en_contexto and t == "mexico":
        return "15"
    clave = _POR_NOMBRE.get(t)
    return None if clave == AREA_NACIONAL and en_contexto else clave


def _ficha(clave: str) -> dict[str, str]:
    return {"clave": clave, "nombre": municipios()[clave], "estado": ESTADOS[clave[:2]]}


def buscar_municipios(texto: str, estado: str | None = None) -> list[dict[str, str]]:
    """Municipios que coinciden con `texto`, del mejor nivel de coincidencia disponible.

    Niveles: nombre exacto > el nombre empieza con el texto ("naucalpan" -> "Naucalpan de
    Juárez") > todas las palabras del texto aparecen en el nombre. Se devuelve solo el mejor
    nivel con resultados, para que "Juárez" no arrastre a todos los "Benito Juárez".
    """
    q = normalizar(texto)
    for prefijo in _PREFIJOS:
        if q.startswith(prefijo):
            q = q[len(prefijo):]
            break
    if not q:
        return []

    clave_estado = None
    if estado:
        clave_estado = _estado(estado, en_contexto=True)
        if clave_estado is None:
            raise ValueError(f"No reconozco el estado '{estado}'.")

    universo = [
        (clave, nombre)
        for clave, nombre in _municipios_normalizados()
        if clave_estado is None or clave.startswith(clave_estado)
    ]
    palabras = q.split()
    niveles = (
        lambda n: n == q,
        lambda n: n.startswith(q + " "),
        lambda n: all(p in n.split() for p in palabras),
    )
    for coincide in niveles:
        encontrados = [clave for clave, nombre in universo if coincide(nombre)]
        if encontrados:
            return [_ficha(c) for c in encontrados]
    return []


def resolver_area(area: str | None) -> str:
    """Convierte un nombre o clave de área geográfica a la clave que espera la API.

    Acepta "00"/"nacional", la clave de estado con o sin cero ("9" o "09"), el nombre del
    estado ("Jalisco", "CDMX", "Edomex"), la clave de municipio de 5 dígitos ("15057") o su
    nombre ("Naucalpan", "Benito Juárez, CDMX"). Si un nombre es a la vez estado y municipio
    ("Aguascalientes", "Hidalgo") gana el estado; para el municipio, "Hidalgo, Michoacán".
    "México" a secas se toma como el país; el estado es "Estado de México" o "15".
    """
    if area is None or not str(area).strip():
        return AREA_NACIONAL
    texto = str(area).strip()

    if texto.isdigit():
        if len(texto) <= 2:
            clave = texto.zfill(2)
            if clave == AREA_NACIONAL or clave in ESTADOS:
                return clave
        elif len(texto) == 5 and texto in municipios():
            return texto
        raise ValueError(
            f"Clave de área '{texto}' no válida. Usa '00' (nacional), 2 dígitos para estado "
            "(p. ej. '09') o 5 dígitos para municipio (estado + municipio, p. ej. '15057')."
        )

    if "," in texto:
        nombre, _, estado = texto.rpartition(",")
        candidatos = buscar_municipios(nombre, estado)
    else:
        clave = _POR_NOMBRE.get(normalizar(texto))
        if clave is not None:
            return clave
        candidatos = buscar_municipios(texto)

    if len(candidatos) == 1:
        return candidatos[0]["clave"]
    if candidatos:
        raise AreaAmbiguaError(texto, candidatos)
    raise ValueError(
        f"No reconozco el área '{texto}'. Usa el nombre de un estado o municipio "
        "('Jalisco', 'Naucalpan', 'Benito Juárez, CDMX') o su clave numérica."
    )
