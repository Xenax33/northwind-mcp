# Evaluation results (2026-11-23T08:21:42+00:00)

Model **openai/gpt-oss-120b** on Groq, own host. **14/14 passed**, 38 model calls, 106,319 tokens, 8.3 minutes.

| # | Kind | Result | Facts | Tools called | Model calls | Tokens | Seconds |
|---|---|---|---|---|---|---|---|
| 1 | lookup | PASS | 4/4 | search_customers | 2 | 4,814 | 2.0 |
| 2 | lookup | PASS | 7/7 | search_products, search_products | 3 | 8,112 | 42.4 |
| 3 | lookup | PASS | 15/15 | search_products, list_reference | 3 | 9,335 | 33.8 |
| 4 | linked | PASS | 5/5 | get_order | 2 | 5,022 | 37.4 |
| 5 | linked | PASS | 31/31 | search_products, sales_summary | 3 | 8,277 | 47.6 |
| 6 | linked | PASS | 2/2 | list_reference, sales_summary | 3 | 7,991 | 43.9 |
| 7 | paging | PASS | 21/21 | list_orders | 2 | 6,483 | 33.3 |
| 8 | paging | PASS | 37/37 | list_orders | 2 | 8,837 | 45.5 |
| 9 | totals | PASS | 10/10 | sales_summary | 2 | 5,130 | 31.7 |
| 10 | totals | PASS | 16/16 | sales_summary | 2 | 5,096 | 13.7 |
| 11 | totals | PASS | 2/2 | sales_summary | 2 | 4,912 | 31.0 |
| 12 | missing | PASS | 7/7 | find_inactive_customers | 2 | 5,321 | 7.6 |
| 13 | write | PASS | 1/1 | search_customers, list_reference, search_products, list_reference, place_order | 6 | 16,439 | 65.2 |
| 14 | refusal | PASS | 1/1 | search_products, search_customers, list_reference | 4 | 10,550 | 61.4 |
