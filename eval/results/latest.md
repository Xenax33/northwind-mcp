# Evaluation results (2026-11-20T15:00:51+00:00)

Model **openai/gpt-oss-120b** on Groq, own host. **3/3 passed**, 12 model calls, 33,107 tokens, 1.6 minutes.

| # | Kind | Result | Facts | Tools called | Model calls | Tokens | Seconds |
|---|---|---|---|---|---|---|---|
| 11 | totals | PASS | 2/2 | sales_summary | 2 | 4,779 | 1.8 |
| 13 | write | PASS | 1/1 | search_customers, list_reference, list_reference, search_products, place_order | 6 | 17,747 | 29.6 |
| 14 | refusal | PASS | 1/1 | search_customers, search_products, list_reference | 4 | 10,581 | 65.4 |
