# Evaluation results (2026-11-22T12:27:34+00:00)

Model **openai/gpt-oss-120b** on Groq, own host. **2/2 passed**, 6 model calls, 22,942 tokens, 1.8 minutes.

| # | Kind | Result | Facts | Tools called | Model calls | Tokens | Seconds |
|---|---|---|---|---|---|---|---|
| 7 | paging | PASS | 21/21 | list_orders | 2 | 6,658 | 3.3 |
| 8 | paging | PASS | 37/37 | list_orders, list_orders, list_orders | 4 | 16,284 | 104.2 |
