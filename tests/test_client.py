import pytest

from mcp_inegi.client import (
    InegiAPIError,
    InegiClient,
    InegiNotFoundError,
    _a_numero,
    _fecha_iso,
    resolver_indicador,
)
from tests.conftest import FakeClient


def test_a_numero():
    assert _a_numero("1636604.00000000000000000000") == 1636604
    assert _a_numero("136.0029999999") == 136.003
    assert _a_numero("3.45000000") == 3.45
    assert _a_numero("-0.3100000") == -0.31
    assert _a_numero("") is None
    assert _a_numero(None) is None
    assert _a_numero("N/E") is None


def test_fecha_iso():
    assert _fecha_iso("25/08/2026 12:00:00 a. m.") == "2026-08-25"
    assert _fecha_iso(None) is None


def test_resolver_indicador():
    assert resolver_indicador("INFLACION_ANUAL") == ("INFLACION_ANUAL", "910406", "BIE-BISE")
    assert resolver_indicador("inflacion anual")[0] == "INFLACION_ANUAL"
    assert resolver_indicador("910406")[0] == "INFLACION_ANUAL"
    assert resolver_indicador("123456") == (None, "123456", None)
    with pytest.raises(InegiAPIError):
        resolver_indicador("cosa rara")


async def test_sin_token_avisa(monkeypatch):
    monkeypatch.delenv("INEGI_TOKEN", raising=False)
    with pytest.raises(InegiAPIError, match="INEGI_TOKEN"):
        await InegiClient(token="").consultar("INFLACION_ANUAL")


async def test_consultar_nacional(fake_client):
    r = await fake_client.consultar("INFLACION_ANUAL", observaciones=2)
    assert r["id_indicador"] == "910406"
    assert r["area"] == {"clave": "00", "nombre": "Estados Unidos Mexicanos"}
    assert r["ultimo"] == {"periodo": "2026/09", "valor": 3.45}
    assert [o["periodo"] for o in r["observaciones"]] == ["2026/09", "2026/08"]
    assert r["total_observaciones"] == 3
    assert r["unidad"] == "Variación Porcentual"
    assert r["frecuencia"] == "Mensual"
    assert r["fuente"].startswith("INEGI")
    assert r["ultima_actualizacion"] == "2026-10-09"
    # Siempre se pide la serie completa, nunca reciente=true.
    assert all("/true/" not in ruta for ruta in fake_client.rutas)


async def test_consultar_municipio(fake_client):
    r = await fake_client.consultar("POBLACION_TOTAL", "15057")
    assert r["area"]["nombre"] == "Naucalpan de Juárez, Estado de México"
    assert r["ultimo"] == {"periodo": "2020", "valor": 834434}


async def test_limite_de_observaciones(fake_client):
    r = await fake_client.consultar("INFLACION_ANUAL", observaciones=10_000)
    assert len(r["observaciones"]) == 3
    r = await fake_client.consultar("INFLACION_ANUAL", observaciones=0)
    assert len(r["observaciones"]) == 1


async def test_sin_datos_para_area_sube_a_nacional(fake_client):
    r = await fake_client.consultar("INFLACION_ANUAL", "Jalisco")
    assert r["area"]["clave"] == "00"
    assert r["area_solicitada"] == {"clave": "14", "nombre": "Jalisco"}
    assert r["resumen"].startswith("El INEGI no publica")
    assert "Jalisco" in r["nota"]


async def test_sin_subir_nivel_falla(fake_client):
    with pytest.raises(InegiNotFoundError):
        await fake_client.consultar("INFLACION_ANUAL", "Jalisco", subir_nivel=False)


async def test_municipio_sin_dato_sube_al_estado(fake_client):
    # La población de 15057 existe, pero simulamos un indicador que solo existe por estado.
    from tests.conftest import SERIES

    SERIES.pop("INDICATOR/1002000001/es/15057/false/BISE/2.0")
    try:
        c = type(fake_client)()
        r = await c.consultar("POBLACION_TOTAL", "Naucalpan")
        assert r["area"]["clave"] == "15"
        assert r["area_solicitada"]["nombre"] == "Naucalpan de Juárez, Estado de México"
    finally:
        from tests.conftest import serie

        SERIES["INDICATOR/1002000001/es/15057/false/BISE/2.0"] = serie(
            "1002000001", [("2020", "834434.0000"), ("2010", "833779.0000")], "188", "3", "2"
        )


async def test_area_invalida(fake_client):
    with pytest.raises(InegiAPIError, match="Atlantis"):
        await fake_client.consultar("INFLACION_ANUAL", "Atlantis")


async def test_id_libre_prueba_ambos_bancos(fake_client):
    # 1002000001 está en el catálogo; uno de 6 dígitos sin datos cae a BISE y luego falla.
    with pytest.raises(InegiNotFoundError):
        await fake_client.consultar("123456")
    bancos = [r.split("/")[5] for r in fake_client.rutas if r.startswith("INDICATOR")]
    assert bancos == ["BIE-BISE", "BISE"]


async def test_cache_evita_segunda_consulta(fake_client):
    await fake_client.consultar("INFLACION_ANUAL")
    n = len(fake_client.rutas)
    await fake_client.consultar("INFLACION_ANUAL")
    assert len(fake_client.rutas) == n


async def test_cache_desactivada():
    c = FakeClient(cache_ttl=0)
    await c.consultar("INFLACION_ANUAL")
    n = len(c.rutas)
    await c.consultar("INFLACION_ANUAL")
    assert len(c.rutas) == 2 * n


async def test_cache_acotada():
    c = FakeClient(cache_max_entries=3)
    await c.consultar("POBLACION_TOTAL", "15057")
    assert len(c._cache) <= 3


async def test_cache_catalogos_dura_24h():
    c = FakeClient(cache_ttl=60.0)
    await c.consultar("INFLACION_ANUAL")
    exp_serie = next(exp for k, (exp, _) in c._cache.items() if k.startswith("INDICATOR/"))
    exp_cat = next(exp for k, (exp, _) in c._cache.items() if k.startswith("CL_"))
    assert exp_cat - exp_serie > 80_000


async def test_metadatos(fake_client):
    m = await fake_client.metadatos("INFLACION_ANUAL")
    assert m["nombre_oficial"] == "Índice general"
    assert m["primer_periodo"] == "2026/07"
    assert m["ultimo_periodo"] == "2026/09"
    assert m["cobertura"] == "nacional"
    assert m["tema"] == "Precios"


async def test_error_de_red_no_filtra_el_token(monkeypatch):
    import httpx

    async def falla(self, url, **kw):
        raise httpx.ConnectError(f"no route to {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", falla)
    c = InegiClient(token="secreto-123")
    with pytest.raises(InegiAPIError) as exc:
        await c.consultar("INFLACION_ANUAL")
    assert "secreto-123" not in str(exc.value)


def test_httpx_no_registra_urls_con_token():
    import logging

    import mcp_inegi.client  # noqa: F401

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


async def test_varias_fuentes_se_juntan():
    class Multi(FakeClient):
        async def _fetch(self, ruta):
            return {"CODE": [{"Description": "Censo 2020"}, {"Description": "Conteo 2005 "}]}

    assert await Multi().describir("CL_SOURCE", "2,3", "BISE") == "Censo 2020; Conteo 2005"


@pytest.mark.parametrize(
    "aproximado,clave",
    [
        ("DESMPLEO_ACTIVO", "TASA_DESOCUPACION"),
        ("desempleo", "TASA_DESOCUPACION"),
        ("tasa de desocupación", "TASA_DESOCUPACION"),
        ("INFLACION_ANUAL_GENERAL", "INFLACION_ANUAL"),
        ("inflación subyacente", "INFLACION_SUBYACENTE_ANUAL"),
        ("poblacion", "POBLACION_TOTAL"),
        ("PIB", "PIB_REAL"),
        ("INFLACON_ANUAL", "INFLACION_ANUAL"),
    ],
)
def test_resolver_indicador_aproximado(aproximado, clave):
    assert resolver_indicador(aproximado)[0] == clave


def test_indicador_desconocido_lista_claves_validas():
    with pytest.raises(InegiAPIError, match="TASA_DESOCUPACION"):
        resolver_indicador("precio del aguacate")


async def test_resumen_listo_para_citar(fake_client):
    r = await fake_client.consultar("POBLACION_TOTAL", "15057")
    assert r["resumen"] == (
        "Población total en Naucalpan de Juárez, Estado de México: 834,434 personas (2020). "
        "Fuente: INEGI, Censos y Conteos de Población y Vivienda."
    )
    r = await fake_client.consultar("INFLACION_ANUAL")
    assert r["resumen"].startswith("Inflación anual (INPC general, variación anual %) en Estados")
    assert "3.45 %" in r["resumen"] and "septiembre de 2026" in r["resumen"]
    assert r["banco"] == "Banco de Información Económica del INEGI"


async def test_tasa_desocupacion_estatal_calculada(fake_client):
    r = await fake_client.consultar("desempleo", "Estado de México")
    assert r["nombre"] == "Tasa de desocupación (calculada)"
    assert r["ultimo"] == {"periodo": "2026/02", "valor": pytest.approx(3.0657, abs=1e-3)}
    assert "3.07 %" in r["resumen"] and "2.º trimestre de 2026" in r["resumen"]
    assert "calculo" in r


async def test_tasa_desocupacion_municipio_usa_la_estatal(fake_client):
    r = await fake_client.consultar("desempleo", "Naucalpan")
    assert r["area"]["clave"] == "15"
    assert r["resumen"].startswith("El INEGI no publica")
    assert "3.07 %" in r["resumen"]
