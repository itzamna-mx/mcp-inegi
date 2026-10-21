import pytest

from mcp_inegi.areas import AreaAmbiguaError, buscar_municipios, municipios, resolver_area


def test_catalogo_completo():
    cat = municipios()
    assert len(cat) > 2400
    assert cat["15057"] == "Naucalpan de Juárez"
    assert all(len(c) == 5 and c[:2] <= "32" for c in cat)


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("Naucalpan", "15057"),
        ("naucalpan de juarez", "15057"),
        ("Municipio de Naucalpan", "15057"),
        ("Naucalpan, Edomex", "15057"),
        ("Naucalpan, México", "15057"),
        ("Ecatepec", "15033"),
        ("Benito Juárez, CDMX", "09014"),
        ("Alcaldía Coyoacán", "09003"),
        ("Juárez, Chihuahua", "08037"),
        ("Monterrey", "19039"),
        ("Hidalgo", "13"),  # el estado gana
    ],
)
def test_municipio_por_nombre(entrada, esperado):
    assert resolver_area(entrada) == esperado


def test_nombre_repetido_pide_estado():
    with pytest.raises(AreaAmbiguaError) as exc:
        resolver_area("Benito Juárez")
    claves = {c["clave"] for c in exc.value.candidatos}
    assert {"09014", "23005"} <= claves
    assert "CDMX" in str(exc.value)


def test_exacto_no_arrastra_parciales():
    # "Juárez" exacto existe en varios estados; no deben colarse los "Benito Juárez".
    nombres = {m["nombre"] for m in buscar_municipios("Juárez")}
    assert nombres == {"Juárez"}


def test_buscar_por_palabras_sueltas():
    claves = {m["clave"] for m in buscar_municipios("san pedro garza")}
    assert claves == {"19019"}


def test_estado_desconocido():
    with pytest.raises(ValueError, match="estado"):
        buscar_municipios("Centro", "Narnia")


def test_sin_resultados():
    assert buscar_municipios("Gotham") == []
    with pytest.raises(ValueError, match="Gotham"):
        resolver_area("Gotham")
