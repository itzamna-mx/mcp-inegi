import pytest

from mcp_inegi.resumen import formatear_valor, fuente_corta, periodo_legible


@pytest.mark.parametrize(
    "periodo,frecuencia,esperado",
    [
        ("2026/09", "Mensual", "septiembre de 2026"),
        ("2026/02", "Trimestral", "2.º trimestre de 2026"),
        ("2025", "Quinquenal", "2025"),
        ("2024/07/02", "Quincenal", "2.ª quincena de julio de 2024"),
        (None, None, None),
    ],
)
def test_periodo_legible(periodo, frecuencia, esperado):
    assert periodo_legible(periodo, frecuencia) == esperado


def test_formatear_valor():
    assert formatear_valor(1142994, "Personas") == "1,142,994 personas"
    assert formatear_valor(3.248862, "Porcentaje") == "3.25 %"
    assert formatear_valor(26144132.442, "pesos a precios de 2018", "Millones") == (
        "26,144,132.44 millones de pesos a precios de 2018"
    )
    assert formatear_valor(None) == "sin dato"


def test_fuente_corta():
    assert fuente_corta("Censos 2000; Censos 2010") == "INEGI, Censos 2000"
    assert fuente_corta("INEGI. ENOE") == "INEGI. ENOE"
    assert fuente_corta(None) == "INEGI"
    assert fuente_corta("Censos 2000; Censos 2010; Censo 2020", "2020") == "INEGI, Censo 2020"
    assert fuente_corta("INEGI. ENOE / ETOE / ENOE-N", "2026/09") == "INEGI. ENOE"
