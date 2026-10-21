# mcp-inegi

Servidor MCP para que cualquier asistente de IA (Claude, ChatGPT, Gemini, Cursor o un modelo local)
consulte **indicadores oficiales del INEGI** y conteste citando la fuente: población, inflación,
empleo, PIB e IGAE, a nivel nacional, estatal y, para datos censales, municipal.

Forma parte de [Itzamná](https://inakisobera.me/itzamna/), una familia de servidores MCP de código
abierto sobre los datos públicos de México. Proyecto independiente, sin afiliación con el INEGI.

## Qué puedes preguntarle

- *¿Cuál fue la inflación anual de septiembre?* → 3.45 % (INPC, indicador 910406, periodo 2026/09)
- *¿Cuánta gente vive en Naucalpan?* → 834,434 personas (Censo 2020, municipio 15057)
- *¿Qué estados tienen más población desocupada?* → compara las 32 entidades con la ENOE
- *¿Cómo va el PIB?* → variación anual, PIB real en millones de pesos de 2018 e IGAE mensual

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

`consultar_indicador` acepta las claves del catálogo (`INFLACION_ANUAL`, `POBLACION_TOTAL`,
`TASA_DESOCUPACION`, `PIB_REAL`, `IGAE`…) o cualquier ID numérico del Banco de Indicadores.
Las áreas se pueden dar por nombre o por clave: estados (`Jalisco`, `CDMX`, `14`) y los 2,478
municipios y alcaldías (`Naucalpan`, `Juárez, Chihuahua`, `15057`). Si un nombre existe en varios
estados, como Benito Juárez, el servidor devuelve los candidatos en lugar de adivinar.

## Instalación

1. Pide tu token gratuito en el
   [INEGI](https://www.inegi.org.mx/app/desarrolladores/generatoken/Usuarios/token_Verify).
2. Verifica la conexión:

```bash
export INEGI_TOKEN="tu_token"
uvx mcp-inegi --test
```

3. Agrégalo a tu cliente MCP. En Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "inegi": {
      "command": "uvx",
      "args": ["mcp-inegi"],
      "env": { "INEGI_TOKEN": "tu_token" }
    }
  }
}
```

En Claude Code:

```bash
claude mcp add inegi -e INEGI_TOKEN=tu_token -- uvx mcp-inegi
```

## Servidor remoto

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
- Las respuestas se guardan en caché una hora (`INEGI_CACHE_TTL`, en segundos).

## Desarrollo

```bash
uv venv && uv pip install -e ".[dev]"
pytest
ruff check .
```

Licencia MIT.
