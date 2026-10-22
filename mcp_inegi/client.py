"""Cliente HTTP asíncrono para la API de Indicadores del INEGI (v2.0)."""

from __future__ import annotations

import asyncio
import logging
import os
from difflib import get_close_matches
from time import monotonic
from typing import Any

import httpx

from .areas import normalizar, resolver_area
from .constants import (
    AREA_NACIONAL,
    BANCO_BIE,
    BANCO_BISE,
    INDICADORES,
    INEGI_API_BASE_URL,
    INEGI_TOKEN_HELP_URL,
    PACKAGE_VERSION,
    banco_para,
    nombre_estado,
)
from .resumen import BANCOS, formatear_valor, fuente_corta, periodo_legible

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


# Palabras sueltas que usan las personas (y los modelos chicos) para referirse a un indicador.
_ALIAS_INDICADORES = {
    "desempleo": "TASA_DESOCUPACION",
    "desocupacion": "TASA_DESOCUPACION",
    "paro": "TASA_DESOCUPACION",
    "desocupados": "POBLACION_DESOCUPADA",
    "desempleados": "POBLACION_DESOCUPADA",
    "inflacion": "INFLACION_ANUAL",
    "inpc": "INPC",
    "subyacente": "INFLACION_SUBYACENTE_ANUAL",
    "poblacion": "POBLACION_TOTAL",
    "habitantes": "POBLACION_TOTAL",
    "hombres": "POBLACION_HOMBRES",
    "mujeres": "POBLACION_MUJERES",
    "indigena": "POBLACION_INDIGENA_PCT",
    "extranjeros": "POBLACION_NACIDA_EXTRANJERO",
    "pib": "PIB_REAL",
    "crecimiento": "PIB_VARIACION_ANUAL",
    "igae": "IGAE",
    "pea": "POBLACION_ECONOMICAMENTE_ACTIVA",
}


def _adivinar_clave(texto: str) -> str | None:
    """Clave del catálogo para un nombre aproximado ("desempleo", "DESMPLEO_ACTIVO")."""
    normal = normalizar(texto).replace("_", " ").replace("-", " ")
    parecida = get_close_matches(normal.upper().replace(" ", "_"), INDICADORES, n=1, cutoff=0.8)
    if parecida:
        return parecida[0]
    palabras = normal.split()
    # "inflacion subyacente" debe ganarle a "inflacion": se revisa primero la palabra más rara.
    for palabra in sorted(palabras, key=lambda w: w != "subyacente"):
        alias = get_close_matches(palabra, _ALIAS_INDICADORES, n=1, cutoff=0.8)
        if alias:
            return _ALIAS_INDICADORES[alias[0]]
    return None


def resolver_indicador(indicador: str) -> tuple[str | None, str, str | None]:
    """Devuelve (clave del catálogo o None, id numérico, banco conocido o None).

    Acepta la clave exacta, un ID numérico o un nombre aproximado: los modelos chicos suelen
    inventar claves parecidas ("DESMPLEO_ACTIVO"), y eso no debe tumbar la consulta.
    """
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
    adivinada = _adivinar_clave(texto)
    if adivinada:
        info = INDICADORES[adivinada]
        return adivinada, info["id"], info["banco"]
    raise InegiAPIError(
        f"Indicador '{indicador}' no reconocido. Claves válidas: {', '.join(INDICADORES)}; "
        "o un ID numérico del INEGI."
    )


def _nombre_area(clave: str) -> str:
    if clave == AREA_NACIONAL:
        return "Estados Unidos Mexicanos"
    if len(clave) == 2:
        return nombre_estado(clave)
    from .areas import municipios

    return f"{municipios().get(clave, clave)}, {nombre_estado(clave[:2])}"


def _marcar_aproximacion(resultado: dict[str, Any], clave_solicitada: str) -> dict[str, Any]:
    """Avisa que el dato es de un nivel superior al lugar que se pidió."""
    solicitada = _nombre_area(clave_solicitada)
    usada = (resultado.get("area") or {}).get("nombre") or "un nivel superior"
    nota = f"El INEGI no publica este dato para {solicitada}; se muestra el dato de {usada}."
    return {
        **resultado,
        "resumen": f"{nota} {resultado.get('resumen') or ''}".strip(),
        "area_solicitada": {"clave": clave_solicitada, "nombre": solicitada},
        "nota": nota,
    }


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
        subir_nivel: bool = True,
    ) -> dict[str, Any]:
        """Últimas `observaciones` de un indicador para un área, con su fuente y metadatos.

        Con `subir_nivel` (por defecto), si el área no tiene el dato se usa el de su estado o
        el nacional, con una nota. Las comparaciones lo apagan: ahí sustituir un estado por el
        dato nacional haría pasar una cifra ajena como propia.
        """
        clave, id_indicador, banco = resolver_indicador(indicador)
        try:
            clave_area = resolver_area(area)
        except ValueError as e:
            raise InegiAPIError(str(e)) from None
        n = max(1, min(int(observaciones), MAX_OBSERVACIONES))

        # Si el lugar no tiene dato (la tasa de desempleo no existe por municipio), se sube de
        # nivel —municipio, estado, país— y se dice con claridad que es una aproximación.
        niveles = [clave_area]
        if subir_nivel:
            if len(clave_area) == 5:
                niveles.append(clave_area[:2])
            if clave_area != AREA_NACIONAL:
                niveles.append(AREA_NACIONAL)
        for nivel in niveles:
            try:
                if clave == "TASA_DESOCUPACION" and nivel != AREA_NACIONAL and len(nivel) == 2:
                    resultado = await self._tasa_desocupacion_estatal(nivel, n)
                else:
                    resultado = await self._consultar_en(clave, id_indicador, banco, nivel, n)
            except InegiNotFoundError:
                continue
            if nivel != clave_area:
                resultado = _marcar_aproximacion(resultado, clave_area)
            return resultado
        raise InegiNotFoundError(
            f"El INEGI no tiene datos del indicador {id_indicador} para el área "
            f"'{clave_area}' ni para niveles superiores."
        )

    async def _consultar_en(
        self, clave: str | None, id_indicador: str, banco: str | None, clave_area: str, n: int
    ) -> dict[str, Any]:
        """consultar() para un área concreta; lanza InegiNotFoundError si no hay dato ahí."""
        serie, banco = await self._serie_cruda(id_indicador, clave_area, banco)

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

        area_nombre = area_nombre or (
            "Estados Unidos Mexicanos" if clave_area == AREA_NACIONAL else None
        )
        if area_nombre and len(clave_area) == 5:
            # "Monterrey" a secas es ambiguo para un modelo: se agrega el estado.
            area_nombre = f"{area_nombre}, {nombre_estado(clave_area[:2])}"
        elif len(clave_area) == 2 and clave_area != AREA_NACIONAL:
            area_nombre = nombre_estado(clave_area)
        ultimo = obs[0] if obs else None
        resumen = None
        if ultimo:
            resumen = (
                f"{nombre} en {area_nombre or clave_area}: "
                f"{formatear_valor(ultimo['valor'], unidad, multiplicador)} "
                f"({periodo_legible(ultimo['periodo'], frecuencia)}). "
                f"Fuente: {fuente_corta(fuente, ultimo['periodo'])}."
            )

        return {
            "resumen": resumen,
            "indicador": clave,
            "id_indicador": id_indicador,
            "nombre": nombre,
            "area": {"clave": clave_area, "nombre": area_nombre},
            "unidad": unidad,
            "multiplicador": multiplicador,
            "frecuencia": frecuencia,
            "fuente": fuente,
            "ultima_actualizacion": _fecha_iso(serie.get("LASTUPDATE")),
            "banco": BANCOS.get(banco, banco),
            "ultimo": ultimo,
            "observaciones": obs[:n],
            "total_observaciones": len(obs),
        }

    async def _tasa_desocupacion_estatal(self, estado: str, n: int) -> dict[str, Any]:
        """Tasa de desocupación de un estado: desocupados / PEA, ambas de la ENOE trimestral.

        El INEGI publica la tasa (444612) solo a nivel nacional, pero por estado sí publica
        las dos poblaciones de la misma encuesta, así que el cociente es directo.
        """
        des_info, pea_info = (
            INDICADORES["POBLACION_DESOCUPADA"],
            INDICADORES["POBLACION_ECONOMICAMENTE_ACTIVA"],
        )
        desocupada, pea = await asyncio.gather(
            self._consultar_en(
                "POBLACION_DESOCUPADA", des_info["id"], des_info["banco"], estado, MAX_OBSERVACIONES
            ),
            self._consultar_en(
                "POBLACION_ECONOMICAMENTE_ACTIVA",
                pea_info["id"],
                pea_info["banco"],
                estado,
                MAX_OBSERVACIONES,
            ),
        )
        pea_por_periodo = {o["periodo"]: o["valor"] for o in pea["observaciones"] if o["valor"]}
        obs = [
            {
                "periodo": o["periodo"],
                "valor": round(100 * o["valor"] / pea_por_periodo[o["periodo"]], 6),
            }
            for o in desocupada["observaciones"]
            if o["valor"] is not None and pea_por_periodo.get(o["periodo"])
        ]
        if not obs:
            raise InegiNotFoundError("Sin periodos comunes entre desocupados y PEA.")
        ultimo = obs[0]
        area = desocupada["area"]
        fuente = "INEGI, Encuesta Nacional de Ocupación y Empleo (ENOE)"
        return {
            "resumen": (
                f"Tasa de desocupación en {area['nombre']}: "
                f"{formatear_valor(ultimo['valor'], 'Porcentaje')} "
                f"({periodo_legible(ultimo['periodo'], 'Trimestral')}), calculada como "
                f"población desocupada / población económicamente activa. Fuente: {fuente}."
            ),
            "indicador": "TASA_DESOCUPACION",
            "id_indicador": f"{des_info['id']}/{pea_info['id']}",
            "nombre": "Tasa de desocupación (calculada)",
            "area": area,
            "unidad": "Porcentaje",
            "multiplicador": None,
            "frecuencia": "Trimestral",
            "fuente": fuente,
            "calculo": (
                f"{des_info['id']} (población desocupada) / {pea_info['id']} "
                "(población económicamente activa) × 100"
            ),
            "ultima_actualizacion": desocupada["ultima_actualizacion"],
            "banco": desocupada["banco"],
            "ultimo": ultimo,
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
