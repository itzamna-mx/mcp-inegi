"""Descarga el catálogo de municipios del Marco Geoestadístico del INEGI.

Genera mcp_inegi/data/municipios.json ({"15057": "Naucalpan de Juárez", ...}). El servicio es
público y no pide token; se corre a mano cuando el INEGI publique un marco nuevo.

    python scripts/generar_municipios.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

URL = "https://gaia.inegi.org.mx/wscatgeo/v2/mgem/{:02d}"
DESTINO = Path(__file__).resolve().parent.parent / "mcp_inegi" / "data" / "municipios.json"


def main() -> None:
    municipios: dict[str, str] = {}
    with httpx.Client(timeout=60) as client:
        for ent in range(1, 33):
            r = client.get(URL.format(ent))
            r.raise_for_status()
            datos = r.json()["datos"]
            if not datos:
                raise SystemExit(f"El estado {ent:02d} no devolvió municipios")
            for m in datos:
                municipios[m["cvegeo"]] = m["nomgeo"].strip()
            print(f"{ent:02d}: {len(datos)} municipios")
    DESTINO.write_text(
        json.dumps(dict(sorted(municipios.items())), ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )
    print(f"Total: {len(municipios)} -> {DESTINO}")


if __name__ == "__main__":
    main()
