from mcp_inegi.perfil import perfil_area
from tests.conftest import FakeClient
from tests.test_denue import FakeDenue


async def test_perfil_municipio_con_negocios():
    filas = [
        {"AE": "46", "AG": "15057", "Total": "100"},
        {"AE": "72", "AG": "15057", "Total": "40"},
        {"AE": "31", "AG": "15057", "Total": "5"},
        {"AE": "32", "AG": "15057", "Total": "7"},
        {"AE": "461", "AG": "15057", "Total": "90"},
    ]
    r = await perfil_area(FakeClient(), FakeDenue({"Cuantificar/0/15057/0": filas}), "Naucalpan")
    assert r["area"]["nombre"] == "Naucalpan de Juárez, Estado de México"
    assert "- Población total: 834,434 personas (2020)" in r["resumen"]
    # Solo cuentan los sectores de 2 dígitos; 31 y 32 se suman como manufactura.
    assert r["datos"]["NEGOCIOS"]["total"] == 152
    assert "comercio al por menor 100, restaurantes y hoteles 40, manufactura 12" in r["resumen"]
    # El desempleo de Naucalpan sale del estado, y se dice.
    assert "en Estado de México" in r["resumen"] and "no se publica para este lugar" in r["resumen"]


async def test_perfil_sin_token_denue_omite_negocios():
    denue = FakeDenue({})
    denue.token = ""
    r = await perfil_area(FakeClient(), denue, "15057")
    assert "NEGOCIOS" not in r["datos"]
    assert "Población total" in r["resumen"]


async def test_perfil_suma_mujeres_y_hombres_cuando_el_total_esta_atrasado():
    # Naucalpan: total solo hasta 2020, pero mujeres y hombres de 2025.
    r = await perfil_area(FakeClient(), FakeDenue({}), "Naucalpan")
    assert "- Población total: 834,434 personas (2020)" in r["resumen"]
    assert "- Población total 2025: 839,763 personas (suma de mujeres y hombres" in r["resumen"]
    assert r["datos"]["POBLACION_TOTAL_CALCULADA"]["valor"] == 839763


async def test_perfil_no_suma_si_el_total_esta_al_dia():
    # En el estado el total ya es de 2025: no hay nada que calcular.
    r = await perfil_area(FakeClient(), FakeDenue({}), "15")
    assert "POBLACION_TOTAL_CALCULADA" not in r["datos"]
