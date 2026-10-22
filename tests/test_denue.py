import json

import httpx
import pytest

from mcp_inegi.client import InegiAPIError
from mcp_inegi.denue import DenueClient, _negocio

NEGOCIO = {
    "Id": "11540944",
    "Nombre": "24 FIT CLUB ",
    "Razon_social": "",
    "Clase_actividad": "Centros de acondicionamiento físico del sector privado",
    "CLASE_ACTIVIDAD_ID": "713943",
    "Estrato": "0 a 5 personas",
    "Tipo_vialidad": "CALLE",
    "Calle": "VICENTE GUERRERO",
    "Num_Exterior": "12",
    "Num_Interior": "",
    "Colonia": "PRADERAS DE SAN MATEO",
    "CP": "53228",
    "Ubicacion": "NAUCALPAN DE JUÁREZ          , Naucalpan de Juárez, MÉXICO          ",
    "Telefono": "",
    "Correo_e": "",
    "Sitio_internet": "",
    "Latitud": "19.50299891",
    "Longitud": "-99.27731732",
}


class FakeDenue(DenueClient):
    def __init__(self, respuestas, **kw):
        kw.setdefault("token", "token-de-prueba")
        super().__init__(**kw)
        self.respuestas = respuestas
        self.rutas: list[str] = []

    async def _fetch(self, ruta):
        self.rutas.append(ruta)
        for prefijo, valor in self.respuestas.items():
            if ruta.startswith(prefijo):
                return valor
        return []


def test_ficha_de_negocio_compacta():
    n = _negocio(NEGOCIO)
    assert n["nombre"] == "24 FIT CLUB"
    assert n["direccion"] == (
        "CALLE VICENTE GUERRERO 12, PRADERAS DE SAN MATEO, C.P. 53228, "
        "Naucalpan de Juárez, México"
    )
    assert n["latitud"] == pytest.approx(19.503)
    assert "telefono" not in n and "razon_social" not in n


async def test_contar_municipio_por_texto():
    c = FakeDenue({"Cuantificar/311830/15057/0": [{"AE": "311830", "AG": "15057", "Total": "515"}]})
    r = await c.contar("tortillerías", "Naucalpan")
    assert r["total"] == 515
    assert r["actividad"][0]["codigo"] == "311830"
    assert r["area"] == {"clave": "15057", "nombre": "Naucalpan de Juárez, Estado de México"}
    assert r["otras_actividades_posibles"]


async def test_contar_nacional_suma_estados():
    # Con área "00" el DENUE devuelve 0: hay que pedir "0" y sumar los renglones por estado.
    filas = [
        {"AE": "311830", "AG": "15", "Total": "100"},
        {"AE": "311830", "AG": "20", "Total": "50"},
    ]
    c = FakeDenue({"Cuantificar/311830/0/0": filas})
    r = await c.contar("311830")
    assert c.rutas == ["Cuantificar/311830/0/0"]
    assert r["total"] == 150
    assert r["estados_con_mas"][0] == {"estado": "Estado de México", "clave": "15", "total": 100}


async def test_contar_varios_codigos_y_estrato():
    filas = [
        {"AE": "464111", "AG": "14", "Total": "10"},
        {"AE": "464112", "AG": "14", "Total": "5"},
    ]
    c = FakeDenue({"Cuantificar/464111,464112/14/1": filas})
    r = await c.contar("464111, 464112", "Jalisco", 1)
    assert r["total"] == 15
    assert r["personal"] == "0 a 5 personas"


async def test_buscar_arma_la_ruta_por_nivel():
    c = FakeDenue({"BuscarAreaAct": [NEGOCIO]})
    r = await c.buscar(None, "Naucalpan", actividad="gimnasio", limite=5)
    assert c.rutas == ["BuscarAreaAct/15/057/0/0/0/0/0/0/713943/0/1/5/0"]
    assert r["negocios"][0]["id"] == "11540944"


async def test_buscar_texto_con_espacios_nacional():
    c = FakeDenue({})
    await c.buscar("farmacias similares", "00", limite=3)
    assert c.rutas == ["BuscarAreaAct/00/0/0/0/0/0/0/0/0/farmacias%20similares/1/3/0"]


async def test_buscar_estrato_por_nombre():
    c = FakeDenue({})
    await c.buscar("tacos", "CDMX", estrato=3)
    assert c.rutas == ["BuscarAreaActEstr/09/0/0/0/0/0/0/0/0/tacos/1/20/0/3"]


async def test_cercanos_ordena_por_distancia():
    lejos = {**NEGOCIO, "Id": "2", "Latitud": "19.49", "Longitud": "-99.24"}
    cerca = {**NEGOCIO, "Id": "1", "Latitud": "19.4786", "Longitud": "-99.2396"}
    c = FakeDenue({"Buscar/": [lejos, cerca]})
    r = await c.cercanos(None, 19.4785, -99.2396, radio_m=99999)
    assert c.rutas == ["Buscar/todos/19.47850,-99.23960/5000"]
    assert [n["id"] for n in r["negocios"]] == ["1", "2"]
    assert r["negocios"][0]["distancia_m"] < 20


@pytest.mark.parametrize(
    "llamada",
    [
        lambda c: c.cercanos("x", 40.7, -74.0),
        lambda c: c.contar("xyzzy"),
        lambda c: c.contar("311830", estrato=9),
        lambda c: c.buscar(None, "CDMX"),
        lambda c: c.buscar(None, "CDMX", actividad="31183"),
    ],
)
async def test_errores_de_entrada(llamada):
    with pytest.raises(InegiAPIError):
        await llamada(FakeDenue({}))


async def test_sin_token(monkeypatch):
    monkeypatch.delenv("DENUE_TOKEN", raising=False)
    # El token de Indicadores no debe usarse en silencio para el DENUE.
    monkeypatch.setenv("INEGI_TOKEN", "token-de-indicadores")
    with pytest.raises(InegiAPIError, match="DENUE_TOKEN"):
        await DenueClient(token="").contar("311830")


@pytest.mark.parametrize(
    "cuerpo,esperado",
    [
        (json.dumps([{"Id": "1"}]), [{"Id": "1"}]),
        # Doblemente codificado, como responde con "Accept: application/json".
        (json.dumps(json.dumps([{"Id": "1"}])), [{"Id": "1"}]),
        (json.dumps("No hay resultados. "), []),
        ("No hay resultados.", []),
    ],
)
async def test_fetch_decodifica(monkeypatch, cuerpo, esperado):
    async def get(self, url, **kw):
        return httpx.Response(200, text=cuerpo)

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    assert await DenueClient(token="t")._fetch("Ficha/1") == esperado


@pytest.mark.parametrize(
    "cuerpo,mensaje",
    [
        ("No autorizado. Utilice una clave válida.", "Token del DENUE"),
        (
            "No hay resultados. Se detecta al menos una clave inválida de Actividad.</br>",
            "clave inválida",
        ),
    ],
)
async def test_fetch_errores(monkeypatch, cuerpo, mensaje):
    async def get(self, url, **kw):
        return httpx.Response(200, text=cuerpo)

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    with pytest.raises(InegiAPIError, match=mensaje):
        await DenueClient(token="secreto-xyz")._fetch("Ficha/1")


async def test_error_de_red_no_filtra_el_token(monkeypatch):
    async def falla(self, url, **kw):
        raise httpx.ConnectError(f"no route to {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", falla)
    with pytest.raises(InegiAPIError) as exc:
        await DenueClient(token="secreto-xyz")._fetch("Ficha/1")
    assert "secreto-xyz" not in str(exc.value)
