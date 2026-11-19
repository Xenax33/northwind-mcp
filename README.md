# northwind-mcp

An MCP server and web host that expose the Northwind trading database to AI assistants.
Work in progress for the Devsinc take-home assessment.

## Build the database

```bash
uv run python scripts/build_db.py
```

The script downloads two pinned sources, checks their SHA-256, and writes `data/northwind.db`:
the 830 real Northwind orders, with Microsoft's original freight values restored.
See `DECISIONS.md` for why.
