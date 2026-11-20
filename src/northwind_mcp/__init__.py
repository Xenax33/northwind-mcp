"""Northwind MCP server: exposes the Northwind trading database to AI assistants."""


def main() -> None:
    from northwind_mcp.server import main as run

    run()
