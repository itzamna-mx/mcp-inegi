"""Genera mcp_inegi/data/scian.json a partir de los catálogos oficiales SCIAN del INEGI.

El DENUE clasifica cada negocio con un código SCIAN (sector, subsector, rama, subrama o clase).
Para traducir "tortillerías" a 311830 se guarda, por código, su título y las palabras de los
productos de su índice de bienes y servicios. SCIAN 2023 es la base; el 2018 llena los códigos
que el DENUE todavía usa y el 2023 ya no tiene.

    pip install openpyxl httpx
    python scripts/generar_scian.py
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import httpx
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp_inegi.areas import normalizar

URL = "https://www.inegi.org.mx/contenidos/app/scian/scian_{}_categorias_y_productos.xlsx"
DESTINO = Path(__file__).resolve().parent.parent / "mcp_inegi" / "data" / "scian.json"

# Palabras de relleno del índice ("aceites comestibles, comercio al por menor de").
_RELLENO = {"de", "la", "el", "los", "las", "y", "o", "en", "con", "sin", "para", "por", "a",
            "al", "del", "e", "u"}


def _titulo(texto: object) -> str:
    # Los títulos marcan con "T" las categorías comunes a Norteamérica ("AgriculturaT ").
    return re.sub(r"T\s*$", "", str(texto).strip()).strip()


def _leer(anio: int) -> dict[str, dict]:
    r = httpx.get(URL.format(anio), timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    hoja = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True).worksheets[0]
    catalogo: dict[str, dict] = {}
    actual = None
    for fila in hoja.iter_rows(min_row=3, values_only=True):
        codigo, titulo, indice = fila[0], fila[1], fila[5] if len(fila) > 5 else None
        if codigo is not None and str(codigo).strip():
            codigo = str(codigo).strip()
            # Sectores con guion ("31-33") se expanden a cada código de 2 dígitos.
            m = re.fullmatch(r"(\d\d)-(\d\d)", codigo)
            codigos = [str(c) for c in range(int(m[1]), int(m[2]) + 1)] if m else [codigo]
            if all(c.isdigit() for c in codigos):
                for c in codigos:
                    catalogo[c] = {"n": _titulo(titulo), "p": set()}
                actual = codigos[-1]
        if indice and actual:
            # El producto es lo que va antes de la primera coma: "tortillas de maíz, elaboración".
            # Lo que sigue a "sin" se descarta: "farmacias sin minisúper" no es un minisúper.
            palabras = re.findall(r"\w+", normalizar(str(indice).split(",")[0]))
            catalogo[actual]["p"].update(
                w
                for i, w in enumerate(palabras)
                if w not in _RELLENO and (i == 0 or palabras[i - 1] != "sin")
            )
    return catalogo


def main() -> None:
    base = _leer(2023)
    print(f"SCIAN 2023: {len(base)} códigos")
    agregados = 0
    for codigo, info in _leer(2018).items():
        if codigo not in base:
            base[codigo] = info
            agregados += 1
    print(f"SCIAN 2018: {agregados} códigos que el 2023 ya no tiene")
    salida = {c: {"n": i["n"], "p": " ".join(sorted(i["p"]))} for c, i in sorted(base.items())}
    DESTINO.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")) + "\n",
                       encoding="utf-8")
    print(f"Total: {len(salida)} -> {DESTINO} ({DESTINO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
