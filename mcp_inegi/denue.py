"""Cliente del DENUE: directorio de los más de 5 millones de negocios registrados por el INEGI."""

from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import quote

import httpx

from .actividades import buscar_actividades, ficha_actividad, nombre_actividad
from .areas import resolver_area
from .client import InegiAPIError, InegiClient
from .constants import (
    AREA_NACIONAL,
    DENUE_API_BASE_URL,
    DENUE_TOKEN_HELP_URL,
    ESTRATOS,
    nombre_estado,
)

#: El DENUE no acepta radios mayores ("Radio máximo 5000 metros").
RADIO_MAXIMO = 5000

#: Tope de negocios por respuesta: cada uno ocupa ~300 caracteres en el contexto del modelo.
MAX_NEGOCIOS = 50


def _limpiar(texto: Any) -> str | None:
    if texto is None:
        return None
    limpio = " ".join(str(texto).split()).strip(" ,")
    return limpio or None


def _distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Distancia en metros (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def _negocio(d: dict[str, Any]) -> dict[str, Any]:
    """Ficha compacta de un establecimiento a partir del registro del DENUE."""
    calle = " ".join(
        x for x in (_limpiar(d.get("Tipo_vialidad")), _limpiar(d.get("Calle"))) if x
    )
    numero = _limpiar(d.get("Num_Exterior"))
    interior = _limpiar(d.get("Num_Interior"))
    partes = [
        f"{calle} {numero}".strip() if numero else calle,
        f"int. {interior}" if interior else None,
        _limpiar(d.get("Colonia")),
        f"C.P. {d['CP']}" if _limpiar(d.get("CP")) else None,
    ]
    ubicacion = [_limpiar(u) for u in str(d.get("Ubicacion") or "").split(",")]
    # "NAUCALPAN DE JUÁREZ, Naucalpan de Juárez, MÉXICO": municipio y estado al final.
    if len(ubicacion) >= 3:
        partes += [ubicacion[-2], ubicacion[-1].title() if ubicacion[-1] else None]

    lat, lon = d.get("Latitud"), d.get("Longitud")
    ficha = {
        "id": d.get("Id"),
        "nombre": _limpiar(d.get("Nombre")),
        "razon_social": _limpiar(d.get("Razon_social")),
        "actividad": _limpiar(d.get("Clase_actividad")),
        "codigo_actividad": d.get("CLASE_ACTIVIDAD_ID"),
        "personal": _limpiar(d.get("Estrato")),
        "direccion": ", ".join(p for p in partes if p),
        "telefono": _limpiar(d.get("Telefono")),
        "correo": _limpiar(d.get("Correo_e")),
        "sitio_web": _limpiar(d.get("Sitio_internet")),
        "latitud": float(lat) if lat else None,
        "longitud": float(lon) if lon else None,
        "fecha_alta": _limpiar(d.get("Fecha_Alta")),
    }
    return {k: v for k, v in ficha.items() if v is not None}


class DenueClient(InegiClient):
    """Cliente para la API del DENUE. Comparte la caché y los locks de InegiClient."""

    #: Los cortes del DENUE se publican un par de veces al año.
    DEFAULT_CACHE_TTL = 6 * 3600.0

    TOKEN_ENV = "DENUE_TOKEN"

    def __init__(self, token: str | None = None, **kwargs: Any):
        kwargs.setdefault("timeout", 60.0)
        super().__init__(token=token, **kwargs)

    def _mensaje_sin_token(self) -> str:
        return (
            "No se encontró el token del DENUE (es distinto al de Indicadores). "
            f"Obtén uno gratis en {DENUE_TOKEN_HELP_URL} "
            "y configúralo en la variable de entorno DENUE_TOKEN."
        )

    async def _fetch(self, ruta: str) -> Any:
        url = f"{DENUE_API_BASE_URL}/{ruta}/{self.token}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, headers=self._get_headers())
            except httpx.RequestError as e:
                raise InegiAPIError(
                    f"Error de red al conectar con el DENUE ({type(e).__name__})."
                ) from None

        if response.status_code != 200:
            raise InegiAPIError(f"El DENUE respondió con código HTTP {response.status_code}.")
        texto = response.text
        # Con "Accept: application/json" el DENUE manda el JSON doblemente codificado: un
        # string que adentro trae la lista, o el mensaje de error entre comillas.
        for _ in range(2):
            try:
                datos = json.loads(texto)
            except ValueError:
                break
            if isinstance(datos, (list, dict)):
                return datos
            if not isinstance(datos, str):
                break
            texto = datos
        # Los errores llegan como texto con HTTP 200 ("No autorizado…", "No hay resultados…").
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = " ".join(texto.split())
        if "autorizado" in texto.lower():
            raise InegiAPIError(
                f"Token del DENUE inválido o no activo. Pide uno nuevo en {DENUE_TOKEN_HELP_URL}."
            )
        if texto.lower().startswith("no hay resultados") and "inválida" not in texto:
            return []
        raise InegiAPIError(f"El DENUE respondió: {texto[:300]}")

    # --------------------------------------------------------------- actividad

    @staticmethod
    def _resolver_actividad(actividad: str | None) -> tuple[str | None, list[dict]]:
        """Código SCIAN de 2 a 6 dígitos (o varios separados por comas) a partir de texto."""
        if actividad is None or not str(actividad).strip():
            return None, []
        texto = str(actividad).strip()
        codigos = [c.strip() for c in texto.split(",")]
        if all(c.isdigit() and 2 <= len(c) <= 6 for c in codigos):
            return ",".join(codigos), []
        candidatos = buscar_actividades(texto, limite=5)
        if not candidatos:
            raise InegiAPIError(
                f"No encontré una actividad del SCIAN para '{texto}'. Prueba con otra palabra "
                "o usa buscar_actividad para ver los códigos."
            )
        return candidatos[0]["codigo"], candidatos[1:]

    @staticmethod
    def _resolver_estrato(estrato: str | int | None) -> str:
        if estrato in (None, "", 0, "0"):
            return "0"
        e = str(estrato).strip()
        if e not in ESTRATOS:
            raise InegiAPIError(
                "Estrato no válido. Usa 1 a 7: "
                + "; ".join(f"{k} = {v}" for k, v in ESTRATOS.items())
            )
        return e

    @staticmethod
    def _area(area: str | None) -> tuple[str, str, str]:
        """(clave del área, entidad para la API, municipio de 3 dígitos o '0')."""
        try:
            clave = resolver_area(area)
        except ValueError as e:
            raise InegiAPIError(str(e)) from None
        if clave == AREA_NACIONAL:
            return clave, AREA_NACIONAL, "0"
        if len(clave) == 2:
            return clave, clave, "0"
        return clave, clave[:2], clave[2:]

    # ---------------------------------------------------------------- consultas

    async def contar(
        self, actividad: str, area: str | None = None, estrato: str | int | None = None
    ) -> dict[str, Any]:
        """Número de establecimientos de una actividad en el país, un estado o un municipio."""
        codigo, alternativas = self._resolver_actividad(actividad)
        if codigo is None:
            raise InegiAPIError("Indica la actividad (p. ej. 'tortillerías' o '311830').")
        clave, _, _ = self._area(area)
        e = self._resolver_estrato(estrato)

        # Con área "00" el DENUE devuelve 0; con "0" devuelve un renglón por estado.
        filas = await self._get_json(f"Cuantificar/{codigo}/{'0' if clave == '00' else clave}/{e}")
        por_estado: dict[str, int] = {}
        por_codigo: dict[str, int] = {}
        for f in filas:
            total = int(f.get("Total") or 0)
            por_codigo[f["AE"]] = por_codigo.get(f["AE"], 0) + total
            por_estado[f["AG"]] = por_estado.get(f["AG"], 0) + total

        total = sum(por_codigo.values())
        area_ficha = self._ficha_area(clave)
        nombres = " + ".join(
            f"«{nombre_actividad(c) or c}»" for c in (sorted(por_codigo) or codigo.split(","))
        )
        tamano = f" con {ESTRATOS[e]}" if e in ESTRATOS else ""
        resultado: dict[str, Any] = {
            "resumen": (
                f"En {area_ficha['nombre']} hay {total:,} establecimientos de {nombres}{tamano}, "
                "según el DENUE del INEGI."
            ),
            "total": total,
            "actividad": [
                {**ficha_actividad(c), "total": t} for c, t in sorted(por_codigo.items())
            ]
            or [ficha_actividad(c) for c in codigo.split(",")],
            "area": area_ficha,
            "personal": ESTRATOS.get(e, "todos los tamaños"),
            "fuente": "INEGI, Directorio Estadístico Nacional de Unidades Económicas (DENUE)",
        }
        if clave == AREA_NACIONAL and por_estado:
            top = sorted(por_estado.items(), key=lambda x: x[1], reverse=True)[:5]
            resultado["estados_con_mas"] = [
                {"estado": nombre_estado(k), "clave": k, "total": v} for k, v in top
            ]
        if alternativas:
            resultado["otras_actividades_posibles"] = alternativas
        return resultado

    async def buscar(
        self,
        que: str | None,
        area: str | None = None,
        actividad: str | None = None,
        estrato: str | int | None = None,
        limite: int = 20,
    ) -> dict[str, Any]:
        """Negocios por nombre o giro dentro de un área, opcionalmente filtrados por actividad."""
        clave, entidad, municipio = self._area(area)
        codigo, alternativas = self._resolver_actividad(actividad)
        if codigo and "," in codigo:
            raise InegiAPIError("Para buscar negocios usa un solo código de actividad.")
        e = self._resolver_estrato(estrato)
        n = max(1, min(int(limite), MAX_NEGOCIOS))
        texto = (que or "").strip()
        if not texto and not codigo:
            raise InegiAPIError("Indica qué buscar (nombre o giro) o una actividad.")

        # Filtros por nivel del SCIAN: sector, subsector, rama, (subrama no existe aquí), clase.
        niveles = ["0", "0", "0", "0"]
        if codigo:
            posicion = {2: 0, 3: 1, 4: 2, 6: 3}.get(len(codigo))
            if posicion is None:
                raise InegiAPIError(
                    "Para buscar negocios usa un código de 2, 3, 4 o 6 dígitos (no subrama)."
                )
            niveles[posicion] = codigo
        nombre = quote(texto) if texto else "0"
        base = f"{entidad}/{municipio}/0/0/0/{'/'.join(niveles)}/{nombre}/1/{n}/0"
        ruta = f"BuscarAreaActEstr/{base}/{e}" if e != "0" else f"BuscarAreaAct/{base}"

        negocios = [_negocio(d) for d in await self._get_json(ruta)]
        area_ficha = self._ficha_area(clave)
        que_se_busco = " ".join(
            x for x in (f"«{texto}»" if texto else None,
                        f"de «{nombre_actividad(codigo) or codigo}»" if codigo else None) if x
        )
        resultado: dict[str, Any] = {
            "resumen": (
                (
                    f"Los primeros {len(negocios)} negocios {que_se_busco} en "
                    f"{area_ficha['nombre']} (hay más; el total sale con contar_negocios). "
                    "Fuente: DENUE, INEGI."
                    if len(negocios) == n
                    else f"{len(negocios)} negocios {que_se_busco} en {area_ficha['nombre']}. "
                    "Fuente: DENUE, INEGI."
                )
                if negocios
                else f"No se encontraron negocios {que_se_busco} en {area_ficha['nombre']}."
            ),
            "busqueda": texto or None,
            "area": area_ficha,
            "actividad": ficha_actividad(codigo) if codigo else None,
            "personal": ESTRATOS.get(e, "todos los tamaños"),
            "mostrados": len(negocios),
            "negocios": negocios,
            "fuente": "INEGI, Directorio Estadístico Nacional de Unidades Económicas (DENUE)",
        }
        if len(negocios) == n:
            resultado["nota"] = (
                f"Se muestran los primeros {n}. Para el total usa contar_negocios."
            )
        if alternativas:
            resultado["otras_actividades_posibles"] = alternativas
        return resultado

    async def cercanos(
        self,
        que: str | None,
        latitud: float,
        longitud: float,
        radio_m: int = 1000,
        limite: int = 20,
    ) -> dict[str, Any]:
        """Negocios alrededor de un punto, ordenados del más cercano al más lejano."""
        if not (14.0 <= latitud <= 33.0 and -119.0 <= longitud <= -86.0):
            raise InegiAPIError(
                "Las coordenadas no están en México (latitud 14 a 33, longitud -119 a -86)."
            )
        radio = max(1, min(int(radio_m), RADIO_MAXIMO))
        n = max(1, min(int(limite), MAX_NEGOCIOS))
        texto = (que or "").strip() or "todos"
        # Se redondea a ~1 m para que la caché sirva entre consultas casi iguales.
        ruta = f"Buscar/{quote(texto)}/{latitud:.5f},{longitud:.5f}/{radio}"

        negocios = [_negocio(d) for d in await self._get_json(ruta)]
        for neg in negocios:
            if "latitud" in neg and "longitud" in neg:
                neg["distancia_m"] = _distancia_m(
                    latitud, longitud, neg["latitud"], neg["longitud"]
                )
        negocios.sort(key=lambda x: x.get("distancia_m", 10**9))
        cerca = negocios[0] if negocios else None
        que_se_busco = "" if texto == "todos" else f" «{texto}»"
        return {
            "resumen": (
                f"{len(negocios)} negocios{que_se_busco} a menos de {radio:,} m; el más cercano es "
                f"{cerca.get('nombre')} a {cerca.get('distancia_m', '?')} m (DENUE, INEGI)."
                if cerca
                else f"No hay negocios{que_se_busco} registrados a menos de {radio:,} m."
            ),
            "busqueda": None if texto == "todos" else texto,
            "centro": {"latitud": latitud, "longitud": longitud},
            "radio_m": radio,
            "encontrados": len(negocios),
            "mostrados": min(n, len(negocios)),
            "negocios": negocios[:n],
            "fuente": "INEGI, Directorio Estadístico Nacional de Unidades Económicas (DENUE)",
        }

    @staticmethod
    def _ficha_area(clave: str) -> dict[str, str | None]:
        from .areas import municipios

        if clave == AREA_NACIONAL:
            return {"clave": clave, "nombre": "Estados Unidos Mexicanos"}
        if len(clave) == 2:
            return {"clave": clave, "nombre": nombre_estado(clave)}
        return {
            "clave": clave,
            "nombre": f"{municipios().get(clave)}, {nombre_estado(clave[:2])}",
        }


__all__ = ["DenueClient", "nombre_actividad"]
