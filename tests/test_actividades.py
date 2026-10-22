import pytest

from mcp_inegi.actividades import buscar_actividades, catalogo, nombre_actividad


def test_catalogo_cubre_los_cinco_niveles():
    largos = {len(c) for c in catalogo()}
    assert largos == {2, 3, 4, 5, 6}
    assert nombre_actividad("311830").startswith("Elaboración de tortillas de maíz")
    # Sectores con guion en el SCIAN ("31-33") se expanden a cada código.
    assert nombre_actividad("31") == nombre_actividad("33") == "Industrias manufactureras"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("tortillerías", "311830"),
        ("farmacias", "464111"),
        ("gimnasio", "713943"),
        ("dentista", "621211"),
        ("estética", "812110"),
        ("oxxo", "462112"),
        ("oxxos", "462112"),
        ("dentistas", "621211"),
        ("taquerías", "722514"),
        ("papelería", "465311"),
        ("abarrotes", "461110"),
        ("venta de abarrotes al mayoreo", "431110"),
        ("fabricación de tortillas", "311830"),
        ("taller mecánico", "811111"),
        ("guardería", "624411"),
        ("carnicería", "461121"),
    ],
)
def test_primer_resultado(texto, esperado):
    assert buscar_actividades(texto, 1)[0]["codigo"] == esperado


def test_sin_no_cuenta_como_coincidencia():
    # "Farmacias sin minisúper" no es un minisúper.
    codigos = [a["codigo"] for a in buscar_actividades("minisuper")]
    assert "464111" not in codigos


def test_sin_resultados():
    assert buscar_actividades("xyzzy") == []
    assert buscar_actividades("de la") == []
