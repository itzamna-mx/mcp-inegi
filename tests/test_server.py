import json

import pytest

from mcp_inegi import server as server_mod
from tests.conftest import FakeClient


def _texto(resultado) -> str:
    if isinstance(resultado, tuple):
        resultado = resultado[0]
    if hasattr(resultado, "content"):
        resultado = resultado.content
    return resultado[0].text


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(server_mod, "InegiClient", FakeClient)
    return server_mod.create_server(token="token-de-prueba")


async def test_tools_registradas(server):
    nombres = {t.name for t in await server.list_tools()}
    assert nombres == {
        "indicadores_clave",
        "consultar_indicador",
        "comparar_areas",
        "metadatos_indicador",
    }


async def test_indicadores_clave_filtra_por_tema(server):
    datos = json.loads(_texto(await server.call_tool("indicadores_clave", {"tema": "precios"})))
    assert datos["indicadores"]
    assert all(i["tema"] == "Precios" for i in datos["indicadores"])


async def test_consultar_indicador(server):
    datos = json.loads(
        _texto(await server.call_tool("consultar_indicador", {"indicador": "INFLACION_ANUAL"}))
    )
    assert datos["ultimo"]["valor"] == 3.45
    assert datos["id_indicador"] == "910406"


async def test_consultar_indicador_error_legible(server):
    texto = _texto(
        await server.call_tool(
            "consultar_indicador", {"indicador": "INFLACION_ANUAL", "area": "Jalisco"}
        )
    )
    assert texto.startswith("Error")


async def test_comparar_areas_ordena_y_reporta_errores(server):
    datos = json.loads(
        _texto(
            await server.call_tool(
                "comparar_areas",
                {"indicador": "POBLACION_TOTAL", "areas": ["CDMX", "Edomex", "Jalisco"]},
            )
        )
    )
    res = datos["resultados"]
    assert [r["area"]["clave"] for r in res[:2]] == ["15", "09"]
    assert "error" in res[2]
    assert datos["unidad"] == "Personas"


async def test_comparar_areas_limite(server):
    texto = _texto(
        await server.call_tool(
            "comparar_areas", {"indicador": "POBLACION_TOTAL", "areas": ["09"] * 40}
        )
    )
    assert texto.startswith("Error")
