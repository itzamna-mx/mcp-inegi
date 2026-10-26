"""Perfil de un lugar: las cifras básicas del INEGI y del DENUE en una sola respuesta."""

from __future__ import annotations

import asyncio
from typing import Any

from .actividades import nombre_actividad
from .areas import resolver_area
from .client import InegiAPIError, InegiClient
from .constants import AREA_NACIONAL
from .denue import DenueClient
from .resumen import formatear_valor, periodo_legible

#: (clave del catálogo, etiqueta en el perfil)
_INDICADORES_PERFIL = [
    ("POBLACION_TOTAL", "Población total"),
    ("POBLACION_MUJERES", "Mujeres"),
    ("POBLACION_HOMBRES", "Hombres"),
    ("POBLACION_INDIGENA_PCT", "Se considera indígena"),
    ("POBLACION_NACIDA_EXTRANJERO", "Nacidos en otro país"),
    ("TASA_DESOCUPACION", "Desempleo"),
]


# Nombres cortos de los sectores SCIAN para la frase (el oficial de 72 tiene 85 caracteres).
_SECTOR_CORTO = {
    "11": "agro y pesca", "21": "minería", "22": "electricidad y agua", "23": "construcción",
    "31": "manufactura", "43": "comercio al por mayor", "46": "comercio al por menor",
    "48": "transporte", "51": "medios e informática", "52": "servicios financieros",
    "53": "inmobiliarias y alquiler", "54": "servicios profesionales",
    "56": "servicios de apoyo a negocios", "61": "educación", "62": "salud",
    "71": "esparcimiento y cultura", "72": "restaurantes y hoteles", "81": "otros servicios",
    "93": "gobierno",
}


def _linea(etiqueta: str, r: dict[str, Any]) -> str:
    ultimo = r.get("ultimo") or {}
    valor = formatear_valor(ultimo.get("valor"), r.get("unidad"), r.get("multiplicador"))
    periodo = periodo_legible(ultimo.get("periodo"), r.get("frecuencia"))
    if r.get("area_solicitada"):
        # El dato es del estado o del país: se dice de dónde es.
        return (
            f"- {etiqueta}: {valor} en {r['area']['nombre']} ({periodo}; "
            "no se publica para este lugar)"
        )
    return f"- {etiqueta}: {valor} ({periodo})"


def _suma_por_sexo(datos: dict[str, Any], lineas: list[str]) -> None:
    """Agrega la población del año más reciente cuando el total viene atrasado.

    En los municipios el INEGI publica mujeres y hombres de 2025 (Intercensal) pero el total
    solo hasta 2020 (Censo). Sin esto el perfil mezcla años y las cifras no cuadran.
    """
    total, m, h = (datos.get(k) for k in ("POBLACION_TOTAL", "POBLACION_MUJERES", "POBLACION_HOMBRES"))
    if not (total and m and h):
        return
    periodos = {d["ultimo"]["periodo"] for d in (m, h)}
    if len(periodos) != 1 or {d["area"]["clave"] for d in (total, m, h)} != {total["area"]["clave"]}:
        return
    periodo = periodos.pop()
    if str(periodo) <= str(total["ultimo"]["periodo"]):
        return
    suma = int(m["ultimo"]["valor"]) + int(h["ultimo"]["valor"])
    datos["POBLACION_TOTAL_CALCULADA"] = {"periodo": periodo, "valor": suma, "calculo": "mujeres + hombres"}
    i = next((n for n, x in enumerate(lineas) if x.startswith("- Población total:")), -1)
    lineas.insert(i + 1, f"- Población total {periodo}: {suma:,} personas (suma de mujeres y hombres; "
                         "el INEGI aún no publica el total de ese año para este lugar)")


async def _negocios(denue: DenueClient, clave: str) -> dict[str, Any] | None:
    """Total de establecimientos y giros principales (sectores SCIAN de 2 dígitos)."""
    if not denue.token:
        return None
    try:
        filas = await denue._get_json(f"Cuantificar/0/{'0' if clave == AREA_NACIONAL else clave}/0")
    except InegiAPIError:
        return None
    por_sector: dict[str, int] = {}
    for f in filas:
        if len(f.get("AE", "")) == 2:
            por_sector[f["AE"]] = por_sector.get(f["AE"], 0) + int(f.get("Total") or 0)
    if not por_sector:
        return None
    # El SCIAN junta 31-33 (manufactura) y 48-49 (transporte): se suman para no repetirlos.
    for grupo in (("31", "32", "33"), ("48", "49")):
        presentes = [c for c in grupo if c in por_sector]
        if len(presentes) > 1:
            por_sector[presentes[0]] = sum(por_sector.pop(c) for c in presentes)
    principales = sorted(por_sector.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "total": sum(por_sector.values()),
        "principales": [
            {"sector": c, "nombre": _SECTOR_CORTO.get(c) or nombre_actividad(c), "total": t}
            for c, t in principales
        ],
    }


async def perfil_area(client: InegiClient, denue: DenueClient, area: str | None) -> dict[str, Any]:
    """Población, desempleo y negocios de un lugar, cada cifra con su periodo y fuente."""
    try:
        clave = resolver_area(area)
    except ValueError as e:
        raise InegiAPIError(str(e)) from None

    resultados = await asyncio.gather(
        *(client.consultar(ind, clave) for ind, _ in _INDICADORES_PERFIL),
        _negocios(denue, clave),
        return_exceptions=True,
    )
    *indicadores, negocios = resultados

    nombre_area = None
    datos: dict[str, Any] = {}
    lineas: list[str] = []
    for (ind, etiqueta), r in zip(_INDICADORES_PERFIL, indicadores):
        if isinstance(r, BaseException) or not r.get("ultimo"):
            continue
        nombre_area = nombre_area or (r.get("area_solicitada") or r["area"])["nombre"]
        datos[ind] = {"resumen": r["resumen"], "ultimo": r["ultimo"], "area": r["area"]}
        lineas.append(_linea(etiqueta, r))

    _suma_por_sexo(datos, lineas)

    if isinstance(negocios, dict):
        giros = ", ".join(
            f"{g['nombre'] or g['sector']} {g['total']:,}" for g in negocios["principales"][:3]
        )
        lineas.append(f"- Negocios registrados en el DENUE: {negocios['total']:,} (principales: {giros})")
        datos["NEGOCIOS"] = negocios

    if not lineas:
        raise InegiAPIError(f"El INEGI no tiene datos para el área '{clave}'.")
    nombre_area = nombre_area or DenueClient._ficha_area(clave)["nombre"]
    return {
        "resumen": "\n".join(
            [f"Perfil de {nombre_area} con datos del INEGI:"]
            + lineas
            + ["Fuente: INEGI (Censo 2020, Encuesta Intercensal 2025, ENOE y DENUE)."]
        ),
        "area": {"clave": clave, "nombre": nombre_area},
        "datos": datos,
    }
