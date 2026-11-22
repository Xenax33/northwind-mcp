# AI usage

## Tools I used

- **Claude** (Claude Code in the Claude desktop app, model Opus 5.5). It was my assistant for the whole project. I worked through it one decision at a time: it laid out the options with a recommendation, and I chose.
- **Groq `openai/gpt-oss-120b`** is part of the product, not something I built with: it's the model inside the web host that answers questions.
- I also used **Claude Code** and **MCP Inspector** as test clients for the server (`docs/proof`).

## What I used them for

| Task | Tool | How much of the result I kept |
|---|---|---|
| Reading the brief and listing the decisions to make, with options and trade-offs | Claude | The options, yes. The choices are mine, and in a few places I went against its recommendation (see below). |
| Checking candidate datasets, and finding the padding and overwritten freight in the Northwind file | Claude, running SQL I could re-run | All of it, after re-running its proof queries myself. They're in my decision notes. |
| Checking facts that changed after its training: MCP SDK 2.x (FastMCP renamed to `MCPServer`), the current MCP spec version, Groq's models and limits | Claude, with web search and small test scripts | Only what I could confirm. I read my real Groq limits from the API response headers, not from blog posts. |
| Writing the code: SQL views, MCP server, tools, web host, page, eval runner | Claude | Most of the code is AI-written. I reviewed it, tried every part myself in MCP Inspector and the browser, and asked for changes where it didn't behave as I expected. |
| Writing the tests (108) | Claude | All of them. I ran them myself, including in a fresh clone. |
| Expected answers for the eval | Claude, using raw SQL on the base tables | All of them. They're deliberately computed without the server's views, so they check the server independently. |
| Drafting README, DECISIONS.md and this file | Claude | Drafts, which I edited and trimmed. |

## One thing the AI got wrong

When Claude set up `uv` at the start, it installed it into a per-user Python folder that worked in its own shell but not in mine. Everything looked fine while it ran the commands. Then I tried to start the web host myself, and both `uv run northwind-host` and `python -m uv run northwind-host` failed with "not recognized" / "No module named uv". The README it had written said to fall back to `python -m uv`, which was exactly the command that failed for me.

What I did: I had it fix the install so `uv` lands in a folder that's on PATH, and rewrite the README. It now has a setup guide for a new machine and a troubleshooting table. It also tested a plain-pip route that needs no uv at all in a fresh clone (108 tests passed). I'll be running this on another machine, so I needed instructions that work from scratch, not ones that only work on the machine they were written on.

There were smaller ones too, which I caught by testing rather than trusting:
- It first said some customer names had broken accents. That was only its Windows console's display; the raw bytes were valid UTF-8.
- It suggested a one-line text summary next to structured tool results. The MCP spec says the text should carry the full JSON, because many clients pass only the text to the model.
- Its first eval reported a false failure on Q14, because the "nothing written" check didn't allow for Q13's order earlier in the same run.

## What I did without AI

- **Every decision.** Claude recommended; I chose. Where I went against it:
  - I used a public dataset (Northwind) rather than generating robotics data to fit the brief's story.
  - I made `find_inactive_customers` its own tool rather than a filter on `search_customers`.
  - I tried MCP elicitation for the write first, rather than the preview + token design it recommended, and switched only if it failed in real clients.
- **The views idea.** In a previous project we gave a model predefined database views instead of SQL access. I asked whether its "task tools" design was the same thing, and we ended up combining them: views for the joins and rules, tools on top for parameters, paging and the write.
- **Testing in real clients, myself.** I ran the elicitation spike in Claude Code and MCP Inspector, saw that Claude Code declined without showing anything, and chose to keep elicitation and document that trade-off. I took the proof screenshots and placed the test orders myself.
- **Fixing questions, not lowering the bar.** When Q11's answer was right but left out the amount, I chose to reword the question to ask for it, rather than drop the number from the expected answer. I also reworded Q13 to name the salesperson and shipper, rather than add a chat feature.
- **Business rules.** For example, "needs reordering" counts stock already on order, after Claude explained both definitions with real products.
- **Keeping private data out of the public repo.** I kept the brief out of the repo, and I agreed to crop my screenshots after it pointed out they showed my account name and other session titles.
- **Running and pushing everything.** I made all the commits and pushes, and I kept a private log of every decision and why, so I can explain each one.
