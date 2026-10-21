"""Servidor MCP para indicadores oficiales del INEGI."""

from __future__ import annotations

import asyncio
import json

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as MCPServer

from .client import InegiAPIError, InegiClient
from .constants import ESTADOS, INDICADORES, PACKAGE_VERSION

#: Máximo de áreas por comparación: cada una es una consulta a la API.
MAX_AREAS = 33


def _json(datos: object) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2)


def create_server(token: str | None = None) -> MCPServer:
    """Crea y configura una instancia del servidor MCP para el INEGI."""
    server = MCPServer(
        name="mcp-inegi",
        version=PACKAGE_VERSION,
        instructions=(
            "Servidor MCP para consultar indicadores oficiales del INEGI (Instituto Nacional "
            "de Estadística y Geografía de México): población, inflación (INPC), empleo, PIB "
            "e IGAE, a nivel nacional, estatal y, para los datos censales, municipal. "
            "Empieza con indicadores_clave para ver el catálogo y su cobertura geográfica. "
            "Al contestar, cita siempre el periodo, la fuente y el ID del indicador que "
            "devuelve cada herramienta."
        ),
    )
    client = InegiClient(token=token)

    @server.tool()
    async def indicadores_clave(tema: str | None = None) -> str:
        """Lista los indicadores verificados del catálogo, con su ID y cobertura geográfica.

        Args:
            tema: Filtra por tema (opcional): 'Población', 'Precios', 'Empleo' o
                'Actividad económica'.
        """
        filtro = (tema or "").strip().lower()
        catalogo = [
            {
                "clave": clave,
                "id_indicador": info["id"],
                "nombre": info["nombre"],
                "tema": info["tema"],
                "cobertura": info["cobertura"],
                "descripcion": info["descripcion"],
            }
            for clave, info in INDICADORES.items()
            if not filtro or filtro in info["tema"].lower()
        ]
        return _json(
            {
                "indicadores": catalogo,
                "nota": (
                    "Además de estas claves, consultar_indicador acepta cualquier ID numérico "
                    "del Banco de Indicadores del INEGI."
                ),
            }
        )

    @server.tool()
    async def consultar_indicador(
        indicador: str,
        area: str | None = None,
        observaciones: int = 1,
    ) -> str:
        """Consulta el valor más reciente (o la serie) de un indicador del INEGI.

        Args:
            indicador: Clave del catálogo (p. ej. 'INFLACION_ANUAL', 'POBLACION_TOTAL') o un
                ID numérico del INEGI (p. ej. '910406').
            area: Área geográfica (opcional, por defecto nacional). Acepta el nombre del estado
                ('Jalisco', 'CDMX', 'Estado de México'), su clave de 2 dígitos ('14') o la
                clave de municipio de 5 dígitos ('15057' = Naucalpan).
            observaciones: Cuántos periodos devolver, del más reciente hacia atrás (1 a 120).
        """
        try:
            return _json(await client.consultar(indicador, area, observaciones))
        except InegiAPIError as e:
            return f"Error al consultar el indicador {indicador}: {e}"

    @server.tool()
    async def comparar_areas(indicador: str, areas: list[str]) -> str:
        """Compara el último valor de un indicador entre varios estados o municipios.

        Args:
            indicador: Clave del catálogo o ID numérico del INEGI.
            areas: Lista de áreas (nombres o claves), p. ej. ['CDMX', 'Jalisco', 'Nuevo León'].
                Usa ['estados'] para comparar las 32 entidades.
        """
        if [a.strip().lower() for a in areas] == ["estados"]:
            areas = list(ESTADOS)
        if not areas:
            return "Error: indica al menos un área."
        if len(areas) > MAX_AREAS:
            return f"Error: máximo {MAX_AREAS} áreas por comparación."

        async def una(area: str) -> dict:
            try:
                r = await client.consultar(indicador, area, 1)
            except InegiAPIError as e:
                return {"area": area, "error": str(e)}
            return {
                "area": r["area"],
                "periodo": r["ultimo"]["periodo"] if r["ultimo"] else None,
                "valor": r["ultimo"]["valor"] if r["ultimo"] else None,
                "_meta": r,
            }

        filas = await asyncio.gather(*(una(a) for a in areas))
        meta = next((f.pop("_meta") for f in filas if "_meta" in f), None)
        for f in filas:
            f.pop("_meta", None)
        if meta is None:
            return _json({"indicador": indicador, "resultados": filas})

        validas = [f for f in filas if isinstance(f.get("valor"), (int, float))]
        validas.sort(key=lambda f: f["valor"], reverse=True)
        errores = [f for f in filas if "error" in f or f.get("valor") is None]
        return _json(
            {
                "indicador": meta["indicador"],
                "id_indicador": meta["id_indicador"],
                "nombre": meta["nombre"],
                "unidad": meta["unidad"],
                "multiplicador": meta["multiplicador"],
                "fuente": meta["fuente"],
                "ultima_actualizacion": meta["ultima_actualizacion"],
                "resultados": validas + errores,
            }
        )

    @server.tool()
    async def metadatos_indicador(indicador: str) -> str:
        """Ficha de un indicador: nombre oficial, unidad, frecuencia, fuente y periodo cubierto.

        Args:
            indicador: Clave del catálogo o ID numérico del INEGI.
        """
        try:
            return _json(await client.metadatos(indicador))
        except InegiAPIError as e:
            return f"Error al consultar metadatos de {indicador}: {e}"

    return server
