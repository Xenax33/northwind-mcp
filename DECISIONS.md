# Decision log

## 1. Approach in five lines

I exposed Microsoft's Northwind trading database (the 830 real orders, cleaned) through an MCP server written with the official Python SDK.
It has 10 read tools on my own SQL views and one write, `place_order`, which runs only after a human approves it through MCP elicitation.
A FastAPI host starts the server over stdio, logs every JSON-RPC message from the pipe, and lets a Groq model answer questions with the tools.
An eval script starts its own host on a fresh database and checks 14 questions against answers I computed separately with raw SQL.
I also ran the server in two real clients, Claude Code and MCP Inspector (`docs/proof`).

## 2. Key decisions

| Decision | What else I considered | Why I chose this |
|---|---|---|
| Northwind, only the 830 real orders, with the original freight restored | A made-up robotics dataset; Chinook; the padded file as-is | Real linked records, and a write that can genuinely fail (discontinued, no stock). I didn't want to defend invented data. |
| Tools shaped around tasks, on SQL views, with totals done on the server | A `run_sql` tool; letting the model add up rows | The model never writes SQL or adds up 2,155 lines, so it can't get joins or sums wrong. |
| The write is approved through MCP elicitation, after every check and inside one transaction | A `confirm=true` flag; preview first, then commit with a token | The approval isn't a tool argument, so the model can't fill it in. A client that can't ask can't write. |
| Cursor paging; errors with a `code`, a `message` and a `hint` | `offset`/`limit`; raising plain exceptions | The model can't invent pages, and it can correct itself from the hint. Nothing internal leaks. |
| The host starts the server over stdio and logs the real pipe | Running the server inside the host | It's what the brief asks for, and the log shows the real protocol. |
| The eval checks facts and tool calls in code | An LLM judge | Deterministic and free, and a failure names exactly what's missing. |
| Groq `gpt-oss-120b`, free tier | Gemini's free tier | Free, good at tool calling, and the limits are published. Switching is a config change. |

## 3. Things in the data or the problem that surprised me

- The common Northwind SQLite file has 16,282 orders, but only 830 are real. It had also overwritten the freight on those 830 with a formula. I kept only the real orders and restored the freight from Microsoft's original script.
- 658 order lines were sold below or above today's list price, so revenue has to use the price on the order line.
- Two customers have never ordered, so an "inactive customers" query that starts from Orders misses them.
- Claude Code says it supports elicitation but declines automatically. Nothing gets written, but you can't place orders from it.
- On Groq's free tier, 8,000 tokens per minute is also the largest single request you can send.

## 4. What I tried that did not work

- **The first eval run failed Q14 even though the model was right.** My "nothing written" check didn't allow for Q13's order earlier in the same run. Now each question's change is checked on its own.
- **Q8 failed with HTTP 413** when the model fetched all 37 orders in one request. The host now sends lists as columns plus rows (56% smaller), and Q8 passes.
- **After placing an order, the model asked "Do you approve?"** The result now says plainly that the order was saved.

## 5. Results

`openai/gpt-oss-120b` on Groq, free tier. Every run starts from a fresh database. Details are in `eval/results/`.

| Run | Questions | Passed | Model calls | Tokens |
|---|---|---|---|---|
| 1 | 14 | 12 | 41 | 126,494 |
| 3 | 14 | 13 (Q8: 413) | 36 | 104,920 |
| Final | 14 | _to fill_ | _to fill_ | _to fill_ |

## 6. What I would do with one more week

1. **Run the eval several times and report a pass rate.** The model doesn't answer the same way each time (Q8 passed in run 1 and failed in run 3), so one run says less than five.
2. **Let the host hold a short conversation.** When an order is missing the salesperson or shipper, the model already asks for them, but the page can't take a reply.

## 7. Time spent

| Part | Hours |
|---|---|
| Choosing and cleaning the data | 1 |
| MCP server and tools | 3 |
| Safe write (elicitation tests, transaction, audit) | 3 |
| Web host and page | 1 |
| Evaluation | 2 |
| Real-client proof, README, these documents | 1 |
