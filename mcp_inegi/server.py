"""Servidor MCP para indicadores oficiales y el directorio de negocios (DENUE) del INEGI."""

from __future__ import annotations

import asyncio
import json

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as MCPServer

from .actividades import buscar_actividades
from .areas import buscar_municipios
from .client import InegiAPIError, InegiClient
from .constants import ESTADOS, INDICADORES, PACKAGE_VERSION
from .denue import DenueClient

#: Máximo de áreas por comparación: cada una es una consulta a la API.
MAX_AREAS = 33

#: Tope de municipios en una búsqueda (un texto muy corto puede coincidir con cientos).
MAX_MUNICIPIOS = 50


def _json(datos: object) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2)


def create_server(token: str | None = None, denue_token: str | None = None) -> MCPServer:
    """Crea y configura una instancia del servidor MCP para el INEGI."""
    server = MCPServer(
        name="mcp-inegi",
        version=PACKAGE_VERSION,
        instructions=(
            "Servidor MCP para consultar indicadores oficiales del INEGI (Instituto Nacional "
            "de Estadística y Geografía de México): población, inflación (INPC), empleo, PIB "
            "e IGAE, a nivel nacional, estatal y, para los datos censales, municipal; y el "
            "DENUE, el directorio de más de 5 millones de negocios (buscar_negocios, "
            "negocios_cercanos, contar_negocios). "
            "Empieza con indicadores_clave para ver el catálogo y su cobertura geográfica. "
            "Al contestar, cita siempre el periodo, la fuente y el ID del indicador que "
            "devuelve cada herramienta. En el DENUE, di qué actividad SCIAN se usó: si no es "
            "la que pidió la persona, revisa otras_actividades_posibles o buscar_actividad."
        ),
    )
    client = InegiClient(token=token)
    denue = DenueClient(token=denue_token)

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
                nombre o clave de un municipio ('Naucalpan', 'Benito Juárez, CDMX', '15057').
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
    async def buscar_municipio(nombre: str, estado: str | None = None) -> str:
        """Busca la clave geoestadística (5 dígitos) de un municipio o alcaldía por su nombre.

        Úsala cuando un nombre sea ambiguo o para confirmar la clave antes de consultar.

        Args:
            nombre: Nombre completo o parcial, sin importar acentos ('naucalpan', 'Juárez').
            estado: Estado para acotar la búsqueda (opcional), p. ej. 'Chihuahua' o '08'.
        """
        try:
            encontrados = buscar_municipios(nombre, estado)
        except ValueError as e:
            return f"Error: {e}"
        return _json(
            {
                "busqueda": nombre,
                "estado": estado,
                "total": len(encontrados),
                "municipios": encontrados[:MAX_MUNICIPIOS],
                "fuente": "INEGI, Marco Geoestadístico (catálogo de municipios)",
            }
        )

    @server.tool()
    async def buscar_actividad(descripcion: str) -> str:
        """Busca el código SCIAN de una actividad económica ("tortillerías", "gimnasio").

        El DENUE clasifica cada negocio con un código SCIAN; úsala para elegir el código
        correcto antes de contar o buscar negocios cuando la palabra es ambigua.

        Args:
            descripcion: Giro en lenguaje natural, p. ej. 'farmacias', 'taller mecánico'.
        """
        candidatos = buscar_actividades(descripcion, limite=10)
        return _json(
            {
                "busqueda": descripcion,
                "actividades": candidatos,
                "fuente": "INEGI, SCIAN México 2023",
            }
        )

    @server.tool()
    async def contar_negocios(
        actividad: str,
        area: str | None = None,
        personal: int | None = None,
    ) -> str:
        """Cuenta los negocios de un giro en el país, un estado o un municipio (DENUE).

        Args:
            actividad: Giro en lenguaje natural ('tortillerías', 'farmacias') o código SCIAN
                de 2 a 6 dígitos; varios códigos separados por comas se suman ('464111,464112').
            area: País (por defecto), estado o municipio, por nombre o clave ('Naucalpan').
            personal: Tamaño por personal ocupado (opcional): 1 = 0 a 5, 2 = 6 a 10,
                3 = 11 a 30, 4 = 31 a 50, 5 = 51 a 100, 6 = 101 a 250, 7 = 251 y más.
        """
        try:
            return _json(await denue.contar(actividad, area, personal))
        except InegiAPIError as e:
            return f"Error al contar negocios: {e}"

    @server.tool()
    async def buscar_negocios(
        que: str | None = None,
        area: str | None = None,
        actividad: str | None = None,
        personal: int | None = None,
        limite: int = 20,
    ) -> str:
        """Busca negocios por nombre o giro en el país, un estado o un municipio (DENUE).

        Devuelve nombre, giro, tamaño, dirección, teléfono, correo, sitio web y coordenadas.

        Args:
            que: Texto a buscar en el nombre o la actividad ('Similares', 'tacos'). Opcional si
                se da actividad.
            area: País (por defecto), estado o municipio, por nombre o clave.
            actividad: Filtra por giro ('gimnasio') o código SCIAN de 2, 3, 4 o 6 dígitos.
            personal: Tamaño por personal ocupado, 1 a 7 (ver contar_negocios).
            limite: Máximo de negocios a devolver (1 a 50).
        """
        try:
            return _json(await denue.buscar(que, area, actividad, personal, limite))
        except InegiAPIError as e:
            return f"Error al buscar negocios: {e}"

    @server.tool()
    async def negocios_cercanos(
        latitud: float,
        longitud: float,
        que: str | None = None,
        radio_m: int = 1000,
        limite: int = 20,
    ) -> str:
        """Negocios alrededor de un punto, del más cercano al más lejano (DENUE).

        Args:
            latitud: Latitud del punto, p. ej. 19.4785.
            longitud: Longitud del punto, p. ej. -99.2396.
            que: Nombre o giro a buscar ('cafetería'); vacío trae todos los negocios.
            radio_m: Radio de búsqueda en metros (máximo 5000).
            limite: Máximo de negocios a devolver (1 a 50).
        """
        try:
            return _json(await denue.cercanos(que, latitud, longitud, radio_m, limite))
        except InegiAPIError as e:
            return f"Error al buscar negocios cercanos: {e}"

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
