"""Cliente HTTP asíncrono para la API de Indicadores del INEGI (v2.0)."""

from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic
from typing import Any

import httpx

from .areas import resolver_area
from .constants import (
    AREA_NACIONAL,
    BANCO_BIE,
    BANCO_BISE,
    INDICADORES,
    INEGI_API_BASE_URL,
    INEGI_TOKEN_HELP_URL,
    PACKAGE_VERSION,
    banco_para,
)

# El token del INEGI va en la ruta de la URL, y httpx registra cada URL en INFO: sin esto
# terminaría en los logs del cliente MCP o en el journal del servidor remoto.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

#: Tope de observaciones que devuelve una consulta, para no saturar el contexto del modelo.
MAX_OBSERVACIONES = 120


class InegiAPIError(Exception):
    """Excepción para errores al consultar la API del INEGI."""


class InegiNotFoundError(InegiAPIError):
    """La API respondió ErrorCode 100: no hay datos para ese indicador, área o banco."""


def _a_numero(texto: Any) -> float | int | None:
    """Convierte OBS_VALUE ('1636604.0000…', '3.45000000') a número limpio."""
    if texto is None or texto == "":
        return None
    try:
        valor = float(texto)
    except (TypeError, ValueError):
        return None
    if valor.is_integer() and abs(valor) >= 1000:
        return int(valor)
    # La API arrastra ruido de punto flotante (136.0029999999); 6 decimales sobran.
    return round(valor, 6)


def _fecha_iso(texto: str | None) -> str | None:
    """'25/08/2026 12:00:00 a. m.' -> '2026-08-25'."""
    if not texto:
        return None
    fecha = texto.split()[0]
    partes = fecha.split("/")
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        dia, mes, anio = partes
        return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
    return texto


def resolver_indicador(indicador: str) -> tuple[str | None, str, str | None]:
    """Devuelve (clave del catálogo o None, id numérico, banco conocido o None)."""
    texto = str(indicador).strip()
    clave = texto.upper().replace(" ", "_").replace("-", "_")
    if clave in INDICADORES:
        info = INDICADORES[clave]
        return clave, info["id"], info["banco"]
    if texto.isdigit():
        for k, info in INDICADORES.items():
            if info["id"] == texto:
                return k, texto, info["banco"]
        return None, texto, None
    raise InegiAPIError(
        f"Indicador '{indicador}' no reconocido. Usa una clave de indicadores_clave "
        "(p. ej. 'INFLACION_ANUAL') o un ID numérico del INEGI."
    )


class InegiClient:
    """Cliente para la API de Indicadores del INEGI."""

    #: Las series del INEGI cambian, como mucho, unas veces al mes.
    DEFAULT_CACHE_TTL = 3600.0

    #: Unidades, fuentes, frecuencias y áreas geográficas casi nunca cambian (24 h).
    DEFAULT_CATALOG_CACHE_TTL = 86400.0

    #: Se aceptan IDs y áreas arbitrarias: sin cota, la memoria crecería a voluntad.
    DEFAULT_CACHE_MAX_ENTRIES = 512

    #: Variable de entorno de donde sale el token si no se pasa explícito.
    TOKEN_ENV = "INEGI_TOKEN"

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 20.0,
        cache_ttl: float | None = None,
        cache_max_entries: int | None = None,
    ):
        self.token = token or os.environ.get(self.TOKEN_ENV, "")
        self.timeout = timeout
        if cache_ttl is None:
            cache_ttl = float(os.environ.get("INEGI_CACHE_TTL", self.DEFAULT_CACHE_TTL))
        self.cache_ttl = cache_ttl
        if cache_max_entries is None:
            cache_max_entries = int(
                os.environ.get("INEGI_CACHE_MAX_ENTRIES", self.DEFAULT_CACHE_MAX_ENTRIES)
            )
        self.cache_max_entries = cache_max_entries
        # ruta -> (momento de expiración, JSON)
        self._cache: dict[str, tuple[float, Any]] = {}
        # Un lock por ruta: N peticiones simultáneas en frío hacen una sola consulta.
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ caché

    def _cache_get(self, key: str) -> Any | None:
        entrada = self._cache.get(key)
        if entrada is None:
            return None
        expira_en, valor = entrada
        if monotonic() >= expira_en:
            self._cache.pop(key, None)
            return None
        return valor

    def _cache_put(self, key: str, valor: Any) -> None:
        if self.cache_ttl <= 0:
            return
        ttl = (
            max(self.cache_ttl, self.DEFAULT_CATALOG_CACHE_TTL)
            if key.startswith("CL_")
            else self.cache_ttl
        )
        self._cache[key] = (monotonic() + ttl, valor)
        if len(self._cache) > self.cache_max_entries:
            for viejo in list(self._cache)[: len(self._cache) - self.cache_max_entries]:
                self._cache.pop(viejo, None)
        if len(self._locks) > self.cache_max_entries:
            for viejo in list(self._locks):
                if len(self._locks) <= self.cache_max_entries:
                    break
                lock = self._locks.get(viejo)
                if lock is not None and not lock.locked():
                    self._locks.pop(viejo, None)

    # ------------------------------------------------------------------- HTTP

    def _get_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": f"mcp-inegi/{PACKAGE_VERSION} (https://github.com/itzamna-mx/mcp-inegi)",
        }

    def _mensaje_sin_token(self) -> str:
        return (
            "No se encontró el token del INEGI. "
            f"Obtén tu token gratuito en {INEGI_TOKEN_HELP_URL} "
            "y configúralo en la variable de entorno INEGI_TOKEN."
        )

    async def _get_json(self, ruta: str) -> Any:
        """GET a `{base}/{ruta}/{token}?type=json`, con caché por ruta (sin el token)."""
        if not self.token:
            raise InegiAPIError(self._mensaje_sin_token())

        en_cache = self._cache_get(ruta)
        if en_cache is not None:
            return en_cache

        lock = self._locks.setdefault(ruta, asyncio.Lock())
        async with lock:
            en_cache = self._cache_get(ruta)
            if en_cache is not None:
                return en_cache
            datos = await self._fetch(ruta)
            # Solo se cachean respuestas buenas.
            self._cache_put(ruta, datos)
            return datos

    async def _fetch(self, ruta: str) -> Any:
        url = f"{INEGI_API_BASE_URL}/{ruta}/{self.token}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url, params={"type": "json"}, headers=self._get_headers()
                )
            except httpx.RequestError as e:
                # El mensaje de httpx incluye la URL, y la URL lleva el token.
                raise InegiAPIError(
                    f"Error de red al conectar con el INEGI ({type(e).__name__})."
                ) from None

        texto = response.text
        if response.status_code == 400 and "ErrorCode:100" in texto:
            raise InegiNotFoundError("El INEGI no tiene datos para esa combinación.")
        if response.status_code in (401, 403):
            raise InegiAPIError(
                f"Token del INEGI inválido o no autorizado. Verifícalo en {INEGI_TOKEN_HELP_URL}."
            )
        if response.status_code != 200:
            raise InegiAPIError(
                f"El INEGI respondió con código HTTP {response.status_code}: {texto[:200]}"
            )
        try:
            return response.json()
        except ValueError as e:
            raise InegiAPIError(f"Respuesta del INEGI no es JSON válido: {e}") from None

    # ------------------------------------------------------------- catálogos

    async def describir(self, catalogo: str, clave: str | None, banco: str) -> str | None:
        """Descripción de una clave de catálogo (CL_UNIT, CL_FREQ, CL_SOURCE…), o None."""
        if not clave:
            return None
        try:
            datos = await self._get_json(f"{catalogo}/{clave}/es/{banco}/2.0")
            # Una serie puede citar varias fuentes ("2,3,343"): la API las devuelve todas.
            descripciones = [c["Description"].strip() for c in datos["CODE"]]
        except (InegiAPIError, KeyError, TypeError, AttributeError):
            return None
        return "; ".join(d for d in descripciones if d) or None

    # ----------------------------------------------------------------- series

    async def _serie_cruda(
        self, id_indicador: str, area: str, banco: str | None
    ) -> tuple[dict[str, Any], str]:
        """Serie completa de un indicador. Si no se conoce el banco, prueba los dos.

        Se pide siempre la serie completa (reciente=false): con reciente=true la API falla
        cuando el periodo más nuevo no existe para esa área, p. ej. la población de 2025 a
        nivel municipal, aunque el censo 2020 sí esté.
        """
        bancos = [banco] if banco else [banco_para(id_indicador)]
        if not banco:
            bancos.append(BANCO_BIE if bancos[0] == BANCO_BISE else BANCO_BISE)

        for i, b in enumerate(bancos):
            try:
                datos = await self._get_json(f"INDICATOR/{id_indicador}/es/{area}/false/{b}/2.0")
            except InegiNotFoundError:
                if i == len(bancos) - 1:
                    raise
                continue
            series = datos.get("Series") or []
            if series:
                return series[0], b
        raise InegiNotFoundError("El INEGI no devolvió series.")

    async def consultar(
        self,
        indicador: str,
        area: str | None = None,
        observaciones: int = 1,
    ) -> dict[str, Any]:
        """Últimas `observaciones` de un indicador para un área, con su fuente y metadatos."""
        clave, id_indicador, banco = resolver_indicador(indicador)
        try:
            clave_area = resolver_area(area)
        except ValueError as e:
            raise InegiAPIError(str(e)) from None
        n = max(1, min(int(observaciones), MAX_OBSERVACIONES))

        try:
            serie, banco = await self._serie_cruda(id_indicador, clave_area, banco)
        except InegiNotFoundError:
            raise InegiNotFoundError(
                f"El INEGI no tiene datos del indicador {id_indicador} para el área "
                f"'{clave_area}'. Revisa la cobertura en indicadores_clave: varios "
                "indicadores solo existen a nivel nacional."
            ) from None

        obs = [
            {"periodo": o.get("TIME_PERIOD"), "valor": _a_numero(o.get("OBS_VALUE"))}
            for o in serie.get("OBSERVATIONS") or []
        ]
        # La API ya los manda del más reciente al más viejo; se ordena por si acaso.
        obs.sort(key=lambda o: o["periodo"] or "", reverse=True)

        nombre, area_nombre, unidad, multiplicador, frecuencia, fuente = await asyncio.gather(
            self._nombre(clave, id_indicador, banco),
            self.describir("CL_GEO_AREA", clave_area, banco),
            self.describir("CL_UNIT", serie.get("UNIT"), banco),
            self.describir("CL_UNIT_MULT", serie.get("UNIT_MULT"), banco),
            self.describir("CL_FREQ", serie.get("FREQ"), banco),
            self.describir("CL_SOURCE", serie.get("SOURCE"), banco),
        )

        return {
            "indicador": clave,
            "id_indicador": id_indicador,
            "nombre": nombre,
            "area": {
                "clave": clave_area,
                "nombre": area_nombre
                or ("Estados Unidos Mexicanos" if clave_area == AREA_NACIONAL else None),
            },
            "unidad": unidad,
            "multiplicador": multiplicador,
            "frecuencia": frecuencia,
            "fuente": fuente,
            "ultima_actualizacion": _fecha_iso(serie.get("LASTUPDATE")),
            "banco": banco,
            "ultimo": obs[0] if obs else None,
            "observaciones": obs[:n],
            "total_observaciones": len(obs),
        }

    async def _nombre(self, clave: str | None, id_indicador: str, banco: str) -> str | None:
        if clave:
            return INDICADORES[clave]["nombre"]
        return await self.describir("CL_INDICATOR", id_indicador, banco)

    async def metadatos(self, indicador: str) -> dict[str, Any]:
        """Ficha del indicador a nivel nacional: unidad, frecuencia, fuente, periodo cubierto."""
        clave, id_indicador, banco = resolver_indicador(indicador)
        try:
            serie, banco = await self._serie_cruda(id_indicador, AREA_NACIONAL, banco)
        except InegiNotFoundError:
            raise InegiNotFoundError(
                f"El indicador {id_indicador} no existe en el BISE ni en el BIE."
            ) from None

        periodos = sorted(o.get("TIME_PERIOD") or "" for o in serie.get("OBSERVATIONS") or [])
        nombre_oficial, unidad, multiplicador, frecuencia, fuente, tema = await asyncio.gather(
            self.describir("CL_INDICATOR", id_indicador, banco),
            self.describir("CL_UNIT", serie.get("UNIT"), banco),
            self.describir("CL_UNIT_MULT", serie.get("UNIT_MULT"), banco),
            self.describir("CL_FREQ", serie.get("FREQ"), banco),
            self.describir("CL_SOURCE", serie.get("SOURCE"), banco),
            self.describir("CL_TOPIC", serie.get("TOPIC"), banco),
        )
        resultado = {
            "indicador": clave,
            "id_indicador": id_indicador,
            "nombre_oficial": nombre_oficial,
            "unidad": unidad,
            "multiplicador": multiplicador,
            "frecuencia": frecuencia,
            "fuente": fuente,
            "tema": tema,
            "banco": banco,
            "ultima_actualizacion": _fecha_iso(serie.get("LASTUPDATE")),
            "primer_periodo": periodos[0] if periodos else None,
            "ultimo_periodo": periodos[-1] if periodos else None,
            "total_observaciones": len(periodos),
        }
        if clave:
            info = INDICADORES[clave]
            resultado["nombre"] = info["nombre"]
            resultado["descripcion"] = info["descripcion"]
            resultado["cobertura"] = info["cobertura"]
        return resultado
