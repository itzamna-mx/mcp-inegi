"""Frases listas para citar: un modelo chico repite mejor una oración que una tabla de números."""

from __future__ import annotations

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

BANCOS = {
    "BISE": "Banco de Indicadores del INEGI (sociodemográficos)",
    "BIE-BISE": "Banco de Información Económica del INEGI",
}


def periodo_legible(periodo: str | None, frecuencia: str | None = None) -> str | None:
    """'2026/09' -> 'septiembre de 2026'; trimestral '2026/02' -> '2.º trimestre de 2026'."""
    if not periodo:
        return None
    partes = periodo.split("/")
    if len(partes) == 1:
        return partes[0]
    anio, num = partes[0], partes[1]
    if not num.isdigit():
        return periodo
    n = int(num)
    freq = (frecuencia or "").lower()
    if len(partes) == 3 and 1 <= n <= 12 and partes[2].isdigit():
        return f"{partes[2].lstrip('0')}.ª quincena de {MESES[n - 1]} de {anio}"
    if "trimestr" in freq:
        return f"{n}.º trimestre de {anio}"
    if "semestr" in freq:
        return f"{n}.º semestre de {anio}"
    if 1 <= n <= 12:
        return f"{MESES[n - 1]} de {anio}"
    return periodo


def formatear_valor(
    valor: float | None, unidad: str | None = None, multiplicador: str | None = None
) -> str:
    """1142994 -> '1,142,994 personas'; 3.248862 Porcentaje -> '3.25 %'."""
    if valor is None:
        return "sin dato"
    u = (unidad or "").strip()
    if "porcentaje" in u.lower() or "porcentual" in u.lower():
        return f"{valor:,.2f} %"
    if isinstance(valor, int) or float(valor).is_integer():
        texto = f"{int(valor):,}"
    else:
        texto = f"{valor:,.2f}"
    if multiplicador and u:
        return f"{texto} {multiplicador.lower()} de {u.lower()}"
    extra = (multiplicador or u).lower()
    return f"{texto} {extra}".strip()


def fuente_corta(fuente: str | None, periodo: str | None = None) -> str:
    """Una sola fuente para la frase: la del año del dato si la API lista varias.

    Para la población de 2020 la API manda "Censos ... 2000; Censos ... 2010; …; Censo 2020":
    citar la primera haría pensar que el dato es del año 2000.
    """
    if not fuente:
        return "INEGI"
    partes = [p.strip() for p in fuente.split(";") if p.strip()]
    anio = (periodo or "")[:4]
    elegida = next((p for p in partes if anio and anio in p), partes[0] if partes else "")
    # "ENOE / ETOE / ENOE-N": con la primera encuesta basta.
    elegida = elegida.split(" / ")[0].strip()
    return elegida if "INEGI" in elegida.upper() else f"INEGI, {elegida}"
