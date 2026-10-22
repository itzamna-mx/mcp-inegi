"""Interfaz de línea de comandos para mcp-inegi."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from . import __version__
from .client import InegiAPIError, InegiClient
from .constants import DENUE_TOKEN_HELP_URL, INEGI_TOKEN_HELP_URL
from .denue import DenueClient
from .server import create_server


def build_transport_security(allowed_hosts: list[str] | None):
    """Arma la configuración anti DNS-rebinding para los transportes HTTP.

    Detrás de un proxy inverso el header Host que llega es el nombre público,
    que la librería no conoce: sin declararlo responde 421 a cada petición.
    Devolver None deja que la librería aplique su default para loopback.
    """
    if not allowed_hosts:
        return None

    from mcp.server.transport_security import TransportSecuritySettings

    hosts: list[str] = []
    origins: list[str] = []
    for nombre in allowed_hosts:
        # El proxy puede o no incluir el puerto en el Host.
        for entrada in (nombre, f"{nombre}:*"):
            if entrada not in hosts:
                hosts.append(entrada)
        for entrada in (f"https://{nombre}", f"http://{nombre}"):
            if entrada not in origins:
                origins.append(entrada)

    # Conservar loopback para que las pruebas locales sigan funcionando.
    for entrada in ("127.0.0.1:*", "localhost:*", "[::1]:*"):
        if entrada not in hosts:
            hosts.append(entrada)
    for entrada in ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"):
        if entrada not in origins:
            origins.append(entrada)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def test_connection(token: str | None = None, denue_token: str | None = None) -> int:
    """Prueba la API de Indicadores (inflación anual) y, si hay token, la del DENUE."""
    print("=" * 60)
    print(f"mcp-inegi v{__version__} - Verificación de conexión a la API del INEGI")
    print("=" * 60)

    effective_token = token or os.environ.get("INEGI_TOKEN")
    if not effective_token:
        print("\n[AVISO] No se detectó la variable de entorno INEGI_TOKEN.")
        print(f"Para obtener un token gratuito, visita: {INEGI_TOKEN_HELP_URL}\n")
        print("Ejemplo de uso:")
        print('  export INEGI_TOKEN="tu_token_aqui"')
        print("  mcp-inegi\n")
        return 1

    client = InegiClient(token=effective_token)

    async def _run():
        print("Consultando inflación anual (INPC, indicador 910406)...")
        try:
            res = await client.consultar("INFLACION_ANUAL")
            ultimo = res["ultimo"] or {}
            print(f"-> Éxito: periodo {ultimo.get('periodo')}, inflación anual {ultimo.get('valor')} %")
        except InegiAPIError as e:
            print(f"[ERROR] Falló la consulta al INEGI: {e}")
            return 1

        denue = DenueClient(token=denue_token)
        if not denue.token:
            print("\n[AVISO] Sin DENUE_TOKEN: las herramientas de negocios no van a funcionar.")
            print(f"Pide un token gratuito (distinto al de Indicadores) en {DENUE_TOKEN_HELP_URL}")
            return 0
        print("Consultando el DENUE (tortillerías en el país, SCIAN 311830)...")
        try:
            res = await denue.contar("311830")
            print(f"-> Éxito: {res['total']:,} tortillerías registradas")
            return 0
        except InegiAPIError as e:
            print(f"[ERROR] Falló la consulta al DENUE: {e}")
            return 1

    return asyncio.run(_run())


def main() -> None:
    """Punto de entrada principal para el comando mcp-inegi."""
    parser = argparse.ArgumentParser(
        prog="mcp-inegi",
        description=(
            "Servidor MCP comunitario para consultar indicadores oficiales del INEGI. "
            "Parte de Itzamná; proyecto independiente, sin afiliación con el INEGI."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcp-inegi {__version__}")
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Token de la API de Indicadores del INEGI (o configurar variable INEGI_TOKEN)",
    )
    parser.add_argument(
        "--denue-token",
        type=str,
        default=None,
        help="Token de la API del DENUE, distinto al de Indicadores (o variable DENUE_TOKEN)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Verifica la conectividad con la API del INEGI y muestra la inflación anual",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help=(
            "Tipo de transporte MCP (por defecto: stdio). "
            "'streamable-http' sirve el endpoint remoto; 'sse' está deprecado."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host de escucha para transportes HTTP (por defecto: 127.0.0.1)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="HOST",
        help=(
            "Nombre público aceptado en el header Host al correr detrás de un "
            "proxy inverso. Repetible. Sin esto el servidor rechaza con 421."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto de escucha para transportes HTTP (por defecto: 8000)",
    )

    args = parser.parse_args()

    if args.test:
        sys.exit(test_connection(args.token, args.denue_token))

    server = create_server(token=args.token, denue_token=args.denue_token)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        # Detrás de nginx esto se queda en loopback y el proxy publica el TLS.
        server.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            transport_security=build_transport_security(args.allowed_host),
        )


if __name__ == "__main__":
    main()
