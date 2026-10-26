"""Respuestas simuladas de la API del INEGI, con la forma real observada en octubre de 2026."""

from __future__ import annotations

import pytest

from mcp_inegi.client import InegiClient, InegiNotFoundError

CATALOGOS = {
    "CL_GEO_AREA/00": "Estados Unidos Mexicanos",
    "CL_GEO_AREA/15": "México",
    "CL_GEO_AREA/09": "Ciudad de México",
    "CL_GEO_AREA/15057": "Naucalpan de Juárez",
    "CL_UNIT/91": "Variación Porcentual",
    "CL_UNIT/188": "Personas",
    "CL_FREQ/8": "Mensual",
    "CL_FREQ/3": "Quinquenal",
    "CL_FREQ/4": "Trimestral",
    "CL_SOURCE/8": "INEGI. Encuesta Nacional de Ocupación y Empleo (ENOE)",
    "CL_SOURCE/1": "INEGI. Índice Nacional de Precios al Consumidor (INPC)",
    "CL_SOURCE/2": "Censos y Conteos de Población y Vivienda",
    "CL_INDICATOR/910406": "Índice general",
    "CL_INDICATOR/1002000001": "Población total",
    "CL_TOPIC/5": "Precios",
}


def serie(indicador, obs, unit="91", freq="8", source="1", mult=""):
    return {
        "Header": {"Name": "Datos compactos"},
        "Series": [
            {
                "INDICADOR": indicador,
                "FREQ": freq,
                "TOPIC": "5",
                "UNIT": unit,
                "UNIT_MULT": mult,
                "SOURCE": source,
                "LASTUPDATE": "09/10/2026 12:00:00 a. m.",
                "OBSERVATIONS": [
                    {"TIME_PERIOD": p, "OBS_VALUE": v, "COBER_GEO": "0"} for p, v in obs
                ],
            }
        ],
    }


SERIES = {
    "INDICATOR/910406/es/00/false/BIE-BISE/2.0": serie(
        "910406", [("2026/09", "3.45000000"), ("2026/08", "3.57000000"), ("2026/07", "3.51")]
    ),
    "INDICATOR/1002000001/es/00/false/BISE/2.0": serie(
        "1002000001", [("2025", "130911314.0000"), ("2020", "126014024.0000")], "188", "3", "2"
    ),
    "INDICATOR/1002000001/es/15/false/BISE/2.0": serie(
        "1002000001", [("2025", "17612480.0000")], "188", "3", "2"
    ),
    "INDICATOR/1002000001/es/09/false/BISE/2.0": serie(
        "1002000001", [("2025", "9216407.0000")], "188", "3", "2"
    ),
    "INDICATOR/1002000001/es/15057/false/BISE/2.0": serie(
        "1002000001", [("2020", "834434.0000"), ("2010", "833779.0000")], "188", "3", "2"
    ),
    "INDICATOR/1002000003/es/15057/false/BISE/2.0": serie(
        "1002000003", [("2025", "437517.0000"), ("2020", "431939.0000")], "188", "3", "2"
    ),
    "INDICATOR/1002000002/es/15057/false/BISE/2.0": serie(
        "1002000002", [("2025", "402246.0000"), ("2020", "402495.0000")], "188", "3", "2"
    ),
    "INDICATOR/6200093973/es/15/false/BISE/2.0": serie(
        "6200093973", [("2026/02", "256251"), ("2026/01", "270000")], "188", "4", "8"
    ),
    "INDICATOR/6200093960/es/15/false/BISE/2.0": serie(
        "6200093960", [("2026/02", "8358526"), ("2026/01", "8300000")], "188", "4", "8"
    ),
}


class FakeClient(InegiClient):
    """InegiClient con `_fetch` sustituido: registra las rutas pedidas."""

    def __init__(self, **kw):
        kw.setdefault("token", "token-de-prueba")
        super().__init__(**kw)
        self.rutas: list[str] = []

    async def _fetch(self, ruta):
        self.rutas.append(ruta)
        if ruta in SERIES:
            return SERIES[ruta]
        catalogo = ruta.split("/es/")[0]
        if catalogo in CATALOGOS:
            return {"CODE": [{"value": catalogo.split("/")[1], "Description": CATALOGOS[catalogo]}]}
        raise InegiNotFoundError("El INEGI no tiene datos para esa combinación.")


@pytest.fixture
def fake_client():
    return FakeClient()
