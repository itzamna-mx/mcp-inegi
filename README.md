# mcp-inegi

Servidor MCP para que cualquier asistente de IA (Claude, ChatGPT, Gemini, Cursor o un modelo local)
consulte **datos oficiales del INEGI** y conteste citando la fuente:

- **Indicadores:** población, inflación, empleo, PIB e IGAE, a nivel nacional, estatal y, para
  datos censales, municipal.
- **DENUE:** el directorio de más de 5 millones de negocios, con su giro, tamaño, dirección,
  teléfono y coordenadas.

Forma parte de [Itzamná](https://inakisobera.me/itzamna/), una familia de servidores MCP de código
abierto sobre los datos públicos de México. Proyecto independiente, sin afiliación con el INEGI.

## Qué puedes preguntarle

- *¿Cuál fue la inflación anual de septiembre?* → 3.45 % (INPC, indicador 910406, periodo 2026/09)
- *¿Cuánta gente vive en Naucalpan?* → 834,434 personas (Censo 2020, municipio 15057)
- *¿Qué estados tienen más población desocupada?* → compara las 32 entidades con la ENOE
- *¿Cómo va el PIB?* → variación anual, PIB real en millones de pesos de 2018 e IGAE mensual
- *¿Cuántas tortillerías hay en Naucalpan?* → 515 (DENUE, actividad SCIAN 311830)
- *¿Qué cafés hay a 300 m del Zócalo?* → nombre, dirección y distancia de cada uno
- *Dame dentistas en Coyoacán* → nombre, dirección, teléfono y sitio web

Cada respuesta trae el ID del indicador, el periodo, la unidad, la fuente oficial y la fecha de
última actualización, para que cualquiera la pueda verificar.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `indicadores_clave` | Catálogo de indicadores verificados, con su ID y cobertura geográfica |
| `consultar_indicador` | Último valor o serie de un indicador para el país, un estado o un municipio |
| `comparar_areas` | El mismo indicador en varios estados o municipios, ordenado de mayor a menor |
| `buscar_municipio` | Clave de un municipio o alcaldía por nombre, sin importar acentos |
| `metadatos_indicador` | Nombre oficial, unidad, frecuencia, fuente y periodo cubierto |
| `contar_negocios` | Cuántos negocios de un giro hay en el país, un estado o un municipio |
| `buscar_negocios` | Negocios por nombre o giro en un área, con dirección, contacto y tamaño |
| `negocios_cercanos` | Negocios alrededor de unas coordenadas, del más cercano al más lejano |
| `buscar_actividad` | Código SCIAN de un giro ("tortillerías" → 311830) |

`consultar_indicador` acepta las claves del catálogo (`INFLACION_ANUAL`, `POBLACION_TOTAL`,
`TASA_DESOCUPACION`, `PIB_REAL`, `IGAE`…) o cualquier ID numérico del Banco de Indicadores.
Las áreas se pueden dar por nombre o por clave: estados (`Jalisco`, `CDMX`, `14`) y los 2,478
municipios y alcaldías (`Naucalpan`, `Juárez, Chihuahua`, `15057`). Si un nombre existe en varios
estados, como Benito Juárez, el servidor devuelve los candidatos en lugar de adivinar.

Las herramientas del DENUE aceptan el giro en lenguaje natural ("gimnasio", "oxxo", "taller
mecánico"): el servidor lo traduce al código SCIAN con el catálogo oficial incluido en el paquete y
dice qué actividad usó, con alternativas por si no era esa. También se puede filtrar por tamaño
(personal ocupado, de "0 a 5" hasta "251 y más").

## Instalación

### Opción 1: Endpoint remoto (sin instalar nada, sin token)

Hay una instancia pública hospedada en `streamable-http`. No necesitas Python ni pedir tu propio
token del INEGI:

```text
https://itzamna-mcp.duckdns.org/inegi/mcp
```

En Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "inegi": {
      "type": "streamable-http",
      "url": "https://itzamna-mcp.duckdns.org/inegi/mcp"
    }
  }
}
```

En Claude Code:

```bash
claude mcp add --transport http inegi https://itzamna-mcp.duckdns.org/inegi/mcp
```

> Es un servicio comunitario en infraestructura propia, con límite de 30 consultas por minuto por IP.
> Para uso intensivo o en producción, instálalo localmente con tu propio token.

### Opción 2: En tu computadora (con `uvx`)

1. Pide tu token gratuito en el
   [INEGI](https://www.inegi.org.mx/app/desarrolladores/generatoken/Usuarios/token_Verify).
   Para las herramientas de negocios pide además el token del
   [DENUE](https://www.inegi.org.mx/app/api/denue/tokenVerify/tokenverify.html): es otro distinto.
2. Verifica la conexión:

```bash
export INEGI_TOKEN="tu_token"
export DENUE_TOKEN="tu_token_denue"
uvx mcp-inegi --test
```

3. Agrégalo a tu cliente MCP. En Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "inegi": {
      "command": "uvx",
      "args": ["mcp-inegi"],
      "env": { "INEGI_TOKEN": "tu_token", "DENUE_TOKEN": "tu_token_denue" }
    }
  }
}
```

En Claude Code:

```bash
claude mcp add inegi -e INEGI_TOKEN=tu_token -e DENUE_TOKEN=tu_token_denue -- uvx mcp-inegi
```

## Servidor remoto propio

```bash
mcp-inegi --transport streamable-http --host 127.0.0.1 --port 8000 --allowed-host tu.dominio
```

Detrás de un proxy inverso, `--allowed-host` declara el nombre público para la protección contra
DNS rebinding.

## Notas sobre la API del INEGI

Cosas que descubrimos al construirlo (octubre de 2026) y que el servidor ya resuelve por ti:

- El banco económico se llama `BIE-BISE`; con `BIE` a secas la API responde que no hay resultados.
- Se pide siempre la serie completa: con `reciente=true` la API falla en municipios cuando el
  periodo nacional más nuevo (p. ej. 2025) no existe a ese nivel.
- El token va en la URL, así que el servidor silencia los logs de `httpx` para no filtrarlo.
- El catálogo de municipios viene incluido en el paquete (`scripts/generar_municipios.py` lo
  regenera desde el Marco Geoestadístico).
- En el DENUE, el total nacional se pide con área `0` y se suman los estados: con `00` la API
  responde 0. La búsqueda por área sí usa `00` para todo el país, y "todos" no es comodín ahí.
- El DENUE a veces devuelve el JSON doblemente codificado (un string que trae la lista adentro).
- El catálogo SCIAN viene incluido (`scripts/generar_scian.py` lo regenera desde los catálogos
  2023 y 2018 del INEGI; requiere `openpyxl`).
- Si un lugar no tiene el dato (la tasa de desempleo no existe por municipio), se usa el de su
  estado o el nacional y la respuesta lo dice. La tasa de desempleo por estado se calcula como
  población desocupada / población económicamente activa, ambas de la ENOE trimestral.
- Cada respuesta trae un campo `resumen`: una frase lista para citar con la cifra, el periodo y la
  fuente, pensada para que modelos pequeños no tengan que reformatear números.
- Las series se guardan en caché una hora (`INEGI_CACHE_TTL`, en segundos) y los catálogos de
  unidades, fuentes, frecuencias y áreas durante 24 horas.

## Desarrollo

```bash
uv venv && uv pip install -e ".[dev]"
pytest
ruff check .
```

Licencia MIT.
