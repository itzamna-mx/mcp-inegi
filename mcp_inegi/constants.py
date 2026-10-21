"""Constantes y catálogo de indicadores oficiales del INEGI (API de Indicadores v2.0)."""

from __future__ import annotations

import unicodedata
from importlib.metadata import PackageNotFoundError, version

try:  # instalado normalmente
    PACKAGE_VERSION = version("mcp-inegi")
except PackageNotFoundError:  # ejecutado desde el árbol de fuentes
    PACKAGE_VERSION = "0.0.0.dev0"

# URL base de la API de Indicadores. Las rutas siguen el esquema
# INDICATOR/{id}/es/{area}/{reciente}/{banco}/2.0/{token} y CL_*/{clave}/es/{banco}/2.0/{token}.
INEGI_API_BASE_URL = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml"

# Página donde se solicita el token gratuito.
INEGI_TOKEN_HELP_URL = (
    "https://www.inegi.org.mx/app/desarrolladores/generatoken/Usuarios/token_Verify"
)

# Bancos de información. El BIE (económico) cambió de nombre en la API: "BIE" a secas
# ya responde "No se encontraron resultados" para todo; hoy es "BIE-BISE".
BANCO_BISE = "BISE"
BANCO_BIE = "BIE-BISE"

AREA_NACIONAL = "00"

# Claves de entidad federativa del Marco Geoestadístico.
ESTADOS = {
    "01": "Aguascalientes",
    "02": "Baja California",
    "03": "Baja California Sur",
    "04": "Campeche",
    "05": "Coahuila de Zaragoza",
    "06": "Colima",
    "07": "Chiapas",
    "08": "Chihuahua",
    "09": "Ciudad de México",
    "10": "Durango",
    "11": "Guanajuato",
    "12": "Guerrero",
    "13": "Hidalgo",
    "14": "Jalisco",
    "15": "México",
    "16": "Michoacán de Ocampo",
    "17": "Morelos",
    "18": "Nayarit",
    "19": "Nuevo León",
    "20": "Oaxaca",
    "21": "Puebla",
    "22": "Querétaro",
    "23": "Quintana Roo",
    "24": "San Luis Potosí",
    "25": "Sinaloa",
    "26": "Sonora",
    "27": "Tabasco",
    "28": "Tamaulipas",
    "29": "Tlaxcala",
    "30": "Veracruz de Ignacio de la Llave",
    "31": "Yucatán",
    "32": "Zacatecas",
}

# Nombres comunes que no coinciden con el nombre oficial.
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


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
    return " ".join(sin_acentos.lower().split())


_POR_NOMBRE = {_normalizar(nombre): clave for clave, nombre in ESTADOS.items()}
_POR_NOMBRE.update(_ALIAS_ESTADOS)


def resolver_area(area: str | None) -> str:
    """Convierte un nombre o clave de área geográfica a la clave que espera la API.

    Acepta "00"/"nacional", la clave de estado con o sin cero ("9" o "09"), el nombre del
    estado ("Jalisco", "CDMX", "Edomex") o la clave de municipio de 5 dígitos ("15057").
    Nota: "México" a secas se toma como el país; el estado es "Estado de México" o "15".
    """
    if area is None or not str(area).strip():
        return AREA_NACIONAL
    texto = str(area).strip()
    if texto.isdigit():
        if len(texto) <= 2:
            clave = texto.zfill(2)
            if clave == AREA_NACIONAL or clave in ESTADOS:
                return clave
        elif len(texto) == 5 and texto[:2] in ESTADOS:
            return texto
        raise ValueError(
            f"Clave de área '{texto}' no válida. Usa '00' (nacional), 2 dígitos para estado "
            "(p. ej. '09') o 5 dígitos para municipio (estado + municipio, p. ej. '15057')."
        )
    clave = _POR_NOMBRE.get(_normalizar(texto))
    if clave is None:
        raise ValueError(
            f"No reconozco el área '{texto}'. Usa el nombre de un estado o su clave numérica; "
            "para municipios usa la clave de 5 dígitos (estado + municipio, p. ej. '15057')."
        )
    return clave


# Indicadores verificados contra la API (octubre de 2026). Los IDs de 10 dígitos son del
# BISE (sociodemográfico); los de 6, del BIE (económico).
INDICADORES = {
    # Población (Censos y Conteos; nacional, estatal y municipal)
    "POBLACION_TOTAL": {
        "id": "1002000001",
        "banco": BANCO_BISE,
        "nombre": "Población total",
        "tema": "Población",
        "cobertura": "nacional, estatal y municipal",
        "descripcion": "Personas residentes según censos y conteos de población (cada 5 años).",
    },
    "POBLACION_HOMBRES": {
        "id": "1002000002",
        "banco": BANCO_BISE,
        "nombre": "Población total hombres",
        "tema": "Población",
        "cobertura": "nacional, estatal y municipal",
        "descripcion": "Hombres residentes según censos y conteos de población.",
    },
    "POBLACION_MUJERES": {
        "id": "1002000003",
        "banco": BANCO_BISE,
        "nombre": "Población total mujeres",
        "tema": "Población",
        "cobertura": "nacional, estatal y municipal",
        "descripcion": "Mujeres residentes según censos y conteos de población.",
    },
    "POBLACION_INDIGENA_PCT": {
        "id": "6207019014",
        "banco": BANCO_BISE,
        "nombre": "Porcentaje de la población que se considera indígena",
        "tema": "Población",
        "cobertura": "nacional, estatal y municipal",
        "descripcion": "Proporción de la población que se autoadscribe como indígena.",
    },
    "POBLACION_NACIDA_EXTRANJERO": {
        "id": "6200205259",
        "banco": BANCO_BISE,
        "nombre": "Población nacida en otro país residente en México",
        "tema": "Población",
        "cobertura": "nacional, estatal y municipal",
        "descripcion": "Personas residentes en México que nacieron en otro país.",
    },
    # Precios (INPC base 2018, nacional, mensual)
    "INPC": {
        "id": "910392",
        "banco": BANCO_BIE,
        "nombre": "Índice Nacional de Precios al Consumidor (INPC), índice general",
        "tema": "Precios",
        "cobertura": "nacional",
        "descripcion": "Índice general de precios al consumidor, base 2018 = 100, mensual.",
    },
    "INFLACION_ANUAL": {
        "id": "910406",
        "banco": BANCO_BIE,
        "nombre": "Inflación anual (INPC general, variación anual %)",
        "tema": "Precios",
        "cobertura": "nacional",
        "descripcion": "Variación porcentual del INPC general contra el mismo mes del año anterior.",
    },
    "INFLACION_MENSUAL": {
        "id": "910399",
        "banco": BANCO_BIE,
        "nombre": "Inflación mensual (INPC general, variación mensual %)",
        "tema": "Precios",
        "cobertura": "nacional",
        "descripcion": "Variación porcentual del INPC general contra el mes anterior.",
    },
    "INFLACION_SUBYACENTE_ANUAL": {
        "id": "910407",
        "banco": BANCO_BIE,
        "nombre": "Inflación subyacente anual (variación anual %)",
        "tema": "Precios",
        "cobertura": "nacional",
        "descripcion": "Variación anual del índice subyacente: excluye agropecuarios y energéticos.",
    },
    # Empleo (ENOE)
    "TASA_DESOCUPACION": {
        "id": "444612",
        "banco": BANCO_BIE,
        "nombre": "Tasa de desocupación",
        "tema": "Empleo",
        "cobertura": "nacional",
        "descripcion": "Porcentaje de la población económicamente activa sin empleo, mensual (ENOE).",
    },
    "POBLACION_DESOCUPADA": {
        "id": "6200093973",
        "banco": BANCO_BISE,
        "nombre": "Población desocupada de 15 años y más",
        "tema": "Empleo",
        "cobertura": "nacional y estatal",
        "descripcion": "Personas de 15 años y más sin empleo que buscaron trabajo, trimestral (ENOE).",
    },
    "POBLACION_ECONOMICAMENTE_ACTIVA": {
        "id": "6200093960",
        "banco": BANCO_BISE,
        "nombre": "Población económicamente activa de 15 años y más",
        "tema": "Empleo",
        "cobertura": "nacional y estatal",
        "descripcion": "Personas de 15 años y más ocupadas o buscando empleo, trimestral (ENOE).",
    },
    # Actividad económica
    "PIB_REAL": {
        "id": "735879",
        "banco": BANCO_BIE,
        "nombre": "Producto Interno Bruto a precios de 2018",
        "tema": "Actividad económica",
        "cobertura": "nacional",
        "descripcion": "PIB trimestral en millones de pesos a precios constantes de 2018.",
    },
    "PIB_VARIACION_ANUAL": {
        "id": "736183",
        "banco": BANCO_BIE,
        "nombre": "PIB, variación anual (series desestacionalizadas)",
        "tema": "Actividad económica",
        "cobertura": "nacional",
        "descripcion": "Crecimiento porcentual del PIB contra el mismo trimestre del año anterior.",
    },
    "IGAE": {
        "id": "737121",
        "banco": BANCO_BIE,
        "nombre": "Indicador Global de la Actividad Económica (IGAE)",
        "tema": "Actividad económica",
        "cobertura": "nacional",
        "descripcion": "Aproximación mensual al PIB, índice base 2018 = 100 (serie original).",
    },
}


def banco_para(id_indicador: str) -> str:
    """Infiere el banco por la forma del ID: 10 dígitos = BISE, el resto = BIE."""
    return BANCO_BISE if len(id_indicador) == 10 else BANCO_BIE
