# Northwind MCP server and web host

An [MCP](https://modelcontextprotocol.io) server that lets any AI assistant answer questions about the
**Northwind** trading company (customers, orders, products, suppliers, employees, shippers) and place
orders safely. Around it:

- a **web host** that starts the server, lists its tools, answers questions with an LLM, and shows a live log
  of every protocol message;
- an **evaluation** of 14 real questions with independently computed answers;
- **proof** in two real clients, Claude Code and MCP Inspector ([docs/proof](docs/proof/README.md)).

**Live demo: https://northwind-mcp.onrender.com** (free plan: the first visit after 15 idle minutes
takes about a minute to wake up; 20 questions per hour).

Built for the Devsinc take-home assessment. The reasons behind each choice are in
[DECISIONS.md](DECISIONS.md), and how AI was used is in [AI_USAGE.md](AI_USAGE.md).
**Diagrams of every flow** (the architecture, a question, placing an order, paging, the data build, the
evaluation and the data model) are in [docs/how-it-works.md](docs/how-it-works.md).

## At a glance

| | |
|---|---|
| **Server** | Python, official `mcp` SDK 2.3 (`MCPServer`), stdio transport, current spec **2026-07-28** (also works with 2025-11-25 clients) |
| **Tools** | 10 read-only tools and 1 write tool (`place_order`), all with typed input and output schemas |
| **Data** | The real 830-order Northwind dataset in SQLite, cleaned and verified by a reproducible build |
| **Safety** | The write needs a human's approval through MCP elicitation, is checked first, and is all-or-nothing and audited. Reads use a read-only connection |
| **Host** | FastAPI + plain HTML/JS. Groq `openai/gpt-oss-120b` picks the tools; the live log shows the MCP and AI traffic in two lanes |
| **Tests** | 112 tests: the views, every tool, paging, errors, the write, the real protocol, the host end to end, and the eval's checker |
| **Eval** | **14/14** on the final run, 38 model calls ([eval/results/latest.md](eval/results/latest.md)) |
| **Live** | https://northwind-mcp.onrender.com (Render, free plan) |

## Quick start

You need **Python 3.12+**, **[uv](https://docs.astral.sh/uv/getting-started/installation/)** and **Git**.
The web host and the evaluation also need a free [Groq API key](https://console.groq.com/keys).
MCP Inspector (optional) needs Node.js. The step-by-step guide for a new machine is
[below](#setting-up-on-a-new-machine).

```bash
git clone https://github.com/Xenax33/northwind-mcp.git
cd northwind-mcp
uv sync                                   # install exact locked versions
uv run python scripts/build_db.py         # download, clean and verify the database
uv run pytest                             # 112 tests, about 15 seconds, no API key needed
```

### Use the MCP server from any MCP client

The server speaks MCP over stdio: the client starts it as a child process. Point your client at the
`northwind-mcp` command inside the project's virtual environment. Use absolute paths. On macOS/Linux the
executable is `.venv/bin/northwind-mcp`.

**Claude Code / Claude Desktop** (`.mcp.json` in a project, or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "northwind": {
      "command": "C:/path/to/northwind-mcp/.venv/Scripts/northwind-mcp.exe"
    }
  }
}
```

**MCP Inspector:**

```bash
npx @modelcontextprotocol/inspector@2.14.0 .venv/Scripts/northwind-mcp.exe
```

Placing an order needs a client that supports **MCP elicitation** (asking the user). MCP Inspector and this
project's web host do. Clients that can't ask, or decline automatically as Claude Code does today, get a clean
`declined` error and nothing is written.

### Run the web host

```bash
cp .env.example .env                      # Windows: copy .env.example .env   (then put your Groq key in .env)
uv run northwind-host                     # starts the MCP server and serves http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and try one of the example questions. When an order needs approval, a dialog
shows the priced order: **Approve order** writes it, and **Decline** or Escape writes nothing. Orders appear
under "Recent changes".

### Run the evaluation

```bash
uv run python eval/run_eval.py            # all 14 questions, about 10 minutes on Groq's free tier
uv run python eval/run_eval.py --only 9,13
uv run python eval/run_eval.py --url http://127.0.0.1:8000   # against a running host (skips the write)
```

By default the script starts its **own** host on a fresh copy of the pristine database, so results are
reproducible and your working data is never touched. Results go to `eval/results/latest.md` and `.json`.
Earlier runs are kept in `eval/results/runs/`.

### Reset the data

`scripts/build_db.py` writes two files: `data/northwind-clean.db` (pristine, used by tests and the eval)
and `data/northwind.db` (the working copy the server writes orders to). Running the script again resets both.

## Deploy on Render (free)

The repo includes a [Render Blueprint](render.yaml) that deploys the web host, which starts the MCP server
inside the same service, on Render's free plan.

1. Sign in at [render.com](https://render.com) with your GitHub account.
2. Click **New → Blueprint**, pick this repository, and click **Connect**.
3. When it asks for `GROQ_API_KEY`, paste your key. It's stored by Render and never committed.
4. Click **Apply**. The first build installs everything, builds the database (about 2–4 minutes), and
   gives you a URL like `https://northwind-mcp.onrender.com`.

Render asks for a card to verify your identity, even for the free plan (a temporary $1 authorisation that
isn't charged).

What to expect on the free plan:

- It **sleeps after 15 minutes without visitors**, and the next visit wakes it in about a minute.
- The disk is **reset on every restart**, so orders placed by visitors disappear and the demo returns to
  the clean data on its own.
- To protect the free Groq quota, the demo accepts **20 questions per hour** across all visitors
  (`NORTHWIND_MAX_QUESTIONS_PER_HOUR`). Change it in Render's Environment tab.
- Every push to `main` redeploys automatically.
- Everyone sees the same live log, but an order's approval dialog appears only in the browser that asked,
  and the host accepts the answer only from that browser.

## Setting up on a new machine

Step by step, from a machine with nothing installed. The commands are for **Windows** (Command Prompt or
PowerShell). macOS/Linux differences are noted.

**1. Install the tools (once per machine).**

| Tool | How | Check (in a **new** terminal) |
|---|---|---|
| Python 3.12 or newer | [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** in the installer | `python --version` |
| Git | [git-scm.com/downloads](https://git-scm.com/downloads) | `git --version` |
| uv | `python -m pip install uv` (or the [official installer](https://docs.astral.sh/uv/getting-started/installation/)) | `uv --version` |
| Node.js (optional, only for MCP Inspector) | [nodejs.org](https://nodejs.org) | `npx --version` |

Open a **new** terminal after installing, so it picks up the updated PATH.

**2. Get the code and build the database.**

```bash
git clone https://github.com/Xenax33/northwind-mcp.git
cd northwind-mcp
uv sync
uv run python scripts/build_db.py
uv run pytest
```

`build_db.py` downloads about 25 MB the first time (cached in `data/raw/`), so it needs internet access.
`pytest` should end with `112 passed`.

**3. Add your Groq key** (for the web host and the evaluation only).

```bash
copy .env.example .env
notepad .env
```

On macOS/Linux use `cp .env.example .env` and any editor. Put your key after `GROQ_API_KEY=`, with no quotes
and no spaces, and save. `.env` is git-ignored, so the key is never committed.

**4. Run it.**

```bash
uv run northwind-host
```

Open http://127.0.0.1:8000. Stop it with `Ctrl+C`.

### Troubleshooting

| Problem | Fix |
|---|---|
| `'uv' is not recognized` / `uv: command not found` | Run `python -m pip install uv`, then open a **new** terminal. If it still isn't found, use plain pip instead: `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -e . pytest`. Without uv, run everything through the virtual environment: `.venv\Scripts\python.exe scripts\build_db.py`, `.venv\Scripts\python.exe -m pytest`, `.venv\Scripts\northwind-host.exe` (macOS/Linux: `.venv/bin/...`). pip installs the newest compatible versions rather than the exact locked ones |
| `'python' is not recognized` | Python isn't on PATH. Re-run the installer, choose *Modify*, and tick *Add Python to environment variables*, or use `py` instead of `python` |
| `Database not found at ...` | Run `uv run python scripts/build_db.py` first |
| `checksum mismatch` from `build_db.py` | A download was incomplete. Delete `data/raw/` and run the script again |
| The page says `GROQ_API_KEY is not set` | Create `.env` as in step 3 (the file must be named exactly `.env`, not `.env.txt`), then restart the host |
| Answers are slow, or `502` after a long wait | Groq's free tier allows 8,000 tokens per minute. Wait a minute and ask again |
| Port 8000 is already in use | Start on another port: `set PORT=8001` then `uv run northwind-host` (PowerShell: `$env:PORT=8001`; macOS/Linux: `PORT=8001 uv run northwind-host`) |

## How it works

```
 Browser  --HTTP + Server-Sent Events-->  Web host (FastAPI)  --HTTPS-->  Groq (LLM)
                                              |
                                   stdio, JSON-RPC (MCP)       <- every message is logged
                                              |
                                      MCP server (child process)
                                              |
                                  SQLite: our SQL views + tables
```

1. The host starts `python -m northwind_mcp` as a child process and connects as an MCP client. It wraps
   the stdio pipe so every JSON-RPC message, in both directions, goes to the live log exactly as sent.
2. For a question, the host gives the model the server's instructions and tool list. The model asks for
   tools, the host calls them over MCP, and the results go back to the model until it answers.
3. For `place_order`, the server checks and prices the order, then asks the human (MCP elicitation). The
   page shows a dialog, and only **Approve** lets the server write.

### The tools

| Tool | What it answers |
|---|---|
| `search_customers`, `get_customer` | Find customers; one customer's profile, orders and revenue |
| `find_inactive_customers` | Customers with no order since a date, **including those who never ordered** |
| `search_products`, `get_product` | Products by name, category, supplier, stock status; sales of one product |
| `list_orders`, `get_order` | Orders by customer, product, employee, shipper, dates, status (shipped/unshipped/late); one full order |
| `sales_summary` | Ranked totals (revenue, orders, units, freight) by customer, product, category, employee, country, shipper, month or year |
| `list_reference` | Categories, suppliers, employees (with their manager), shippers |
| `list_recent_changes` | The audit log of changes made through the server |
| `place_order` **(writes)** | A new order of 1–25 lines, after the user approves it |

Design rules: the model never writes SQL. Every ID comes with its name. Totals are computed by the
server, not added up by the model. List tools page with an opaque `next_cursor`. Errors carry a fixed
`code`, a `message` and a `hint` saying what to do next.

### Safe by design

- **The approval comes from a human, not the model.** It isn't a tool argument; the server asks the
  client through MCP elicitation. A client that can't ask can't write.
- **Checked before asking.** An unknown ID, a discontinued product or too little stock is refused before
  any dialog appears.
- **All or nothing.** One transaction (`BEGIN IMMEDIATE`) re-checks stock, writes the order and its lines,
  reduces stock and records an `audit_log` row, or rolls everything back.
- **Reads can't write.** Read tools use a read-only SQLite connection.
- **Bad requests are refused cleanly.** Invalid arguments, unknown tools and bad cursors come back as tool
  errors the model can read. Unexpected crashes return only a generic message, so nothing internal leaks.
- **The public API can't skip the human.** Automatic approval is refused (HTTP 403) unless the host was
  started by the evaluation.

## The data

[Northwind](https://github.com/microsoft/sql-server-samples/tree/master/samples/databases/northwind-pubs)
is Microsoft's sample trading database (MIT licence), loaded from the SQLite conversion by
[jpwhite3/northwind-SQLite3](https://github.com/jpwhite3/northwind-SQLite3) (MIT). The build pins both
sources to a commit, checks their SHA-256, and then:

- keeps only the **830 real orders** (the SQLite file is padded with about 15,400 random ones) and drops two
  test customers;
- restores the **original freight** of every order from Microsoft's own script (the padding script had
  overwritten it);
- creates our SQL views and the `audit_log` table, then checks the row counts, foreign keys, every freight
  value, and the published total revenue of **1,265,793.04**.

The questions this data should answer, and why it fits the brief, are in
[docs/questions.md](docs/questions.md).

## Configuration

| Variable | Used by | Default |
|---|---|---|
| `GROQ_API_KEY` | host, eval | none (required for questions) |
| `NORTHWIND_MODEL` | host | `openai/gpt-oss-120b` |
| `NORTHWIND_DB` | server | `data/northwind.db` |
| `HOST`, `PORT` | host | `127.0.0.1`, `8000` |
| `NORTHWIND_MAX_QUESTIONS_PER_HOUR` | host | `0` = no limit (the Render demo uses 20) |
| `NORTHWIND_ALLOW_AUTO_APPROVAL` | host | off. Set only by the evaluation's own host |

## Project layout

```
src/northwind_mcp/      the MCP server
  server.py             the public surface: tool names, arguments, descriptions, annotations
  tools/                the logic, by area: customers, products, orders, reports, audit, write
  views.sql             our SQL views: all joins and business rules (e.g. revenue) live here
  db.py, errors.py, paging.py, models.py
src/northwind_host/     the web host
  app.py                FastAPI routes: tools, events (SSE), ask, approvals, changes
  mcp_link.py           starts the server over stdio; taps every message; approval handling
  agent.py              the LLM loop (Groq) that calls MCP tools
  static/               the page (plain HTML, CSS, JavaScript)
scripts/build_db.py     reproducible database build and verification
eval/                   questions with expected answers, the runner, results
tests/                  pytest suite
docs/                   the question list and the real-client proof
```

## Known limitations

- **Groq's free tier allows 8,000 tokens per minute**, so multi-step questions wait between model calls
  (an order takes about a minute). The client retries automatically.
- **One question at a time.** The host serves one run at a time, so the log and the approval dialog
  belong to that run. On a shared deployment, visitors see each other's questions in the live log.
- **One question, one answer.** There's no follow-up chat, so an order question should name the
  salesperson and shipper. Without them, the model asks for them instead of guessing.
