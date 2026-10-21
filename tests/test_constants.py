import pytest

from mcp_inegi.areas import resolver_area
from mcp_inegi.constants import BANCO_BIE, BANCO_BISE, INDICADORES, banco_para


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (None, "00"),
        ("", "00"),
        ("nacional", "00"),
        ("México", "00"),
        ("0", "00"),
        ("9", "09"),
        ("09", "09"),
        ("CDMX", "09"),
        ("Ciudad de México", "09"),
        ("estado de mexico", "15"),
        ("Edomex", "15"),
        ("  nuevo   LEÓN ", "19"),
        ("Michoacán", "16"),
        ("15057", "15057"),
    ],
)
def test_resolver_area(entrada, esperado):
    assert resolver_area(entrada) == esperado


@pytest.mark.parametrize("entrada", ["33", "123", "99057", "15999", "Atlantis", "1505"])
def test_resolver_area_invalida(entrada):
    with pytest.raises(ValueError):
        resolver_area(entrada)


def test_banco_por_forma_del_id():
    assert banco_para("1002000001") == BANCO_BISE
    assert banco_para("910406") == BANCO_BIE


def test_catalogo_consistente():
    ids = [i["id"] for i in INDICADORES.values()]
    assert len(ids) == len(set(ids))
    for info in INDICADORES.values():
        assert info["banco"] == banco_para(info["id"])
        assert {"nombre", "tema", "cobertura", "descripcion"} <= info.keys()
