# Notas verificadas de la API del INEGI (21 oct 2026)

URL: https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR/{id}/es/{geo}/{reciente}/{BISE|BIE}/2.0/{token}?type=json
- geo: 00 = nacional, 15 = estado (2 dígitos), 15057 = municipio (estado+municipio). "0700" de la doc YA NO sirve.
- reciente: true = solo el último dato; false = serie completa. OJO: OBSERVATIONS viene del más reciente al más viejo.
- Metadatos: CL_INDICATOR/{id}, CL_UNIT/{u}, CL_FREQ/{f}, CL_SOURCE/{s}, CL_NOTE/{n} (/es/BISE/2.0/{token}).
- Error "No se encontraron resultados" (ErrorCode 100, HTTP 400) = id/geo/banco equivocado.
- Con token falso también respondió (no valida estrictamente hoy).

IDs verificados (BISE):
- 1002000001 Población total (anual; 2025 = 130,911,314; Edomex 17,612,480; Naucalpan 15057 censo 2020 = 834,434)
- 1002000002 Población total hombres · 1002000003 mujeres
- 6200093960 PEA 15+ (trimestral, ENOE) · 6200093973 Población desocupada 15+ (trimestral, ENOE; 2026/02 = 1,636,604)
- 6207019014 % población que se considera indígena (2025 = 18.58)
- 6207019016 % población 12+ divorciada · 6200205259 Población nacida en otro país residente en México
Los IDs viejos del BIE (444612, 628194, 910392, 735879…) ya no responden.

## Actualización (21 oct 2026, construyendo el MCP)
- El banco económico ya NO es "BIE": es **"BIE-BISE"**. Con eso responden 628194, 444612, 910392, 735879…
- INPC base 2018: 910392 índice · 910399 var. mensual · 910406 var. anual (3.45 % sep 2026) · 910407 subyacente anual.
- 444612 tasa de desocupación mensual · 735879 PIB real (UNIT_MULT 2 = Millones) · 736183 PIB var. anual · 737121 IGAE.
- reciente=true FALLA en municipio si el último periodo nacional no existe ahí (población 2025): pedir siempre false.
- Estados con 2 dígitos ("09"; "9" falla). CL_GEO_AREA/{clave} da el nombre. CL_UNIT_MULT/{n} da Miles/Millones.
- SOURCE puede venir como lista "2,3,343": CL_SOURCE la acepta y devuelve varias entradas.
- ¡httpx registra la URL (con token) en INFO! El cliente sube su logger a WARNING.
