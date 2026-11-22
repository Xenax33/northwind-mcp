# How it works, in pictures

GitHub draws these diagrams automatically. Each one has a short explanation underneath.

## 1. The pieces and how they connect

```mermaid
flowchart LR
    U([Employee<br/>in a browser])
    C([Claude Code /<br/>MCP Inspector])
    G[(Groq<br/>gpt-oss-120b)]
    subgraph HOST["Web host (FastAPI)"]
        R[app.py<br/>routes]
        A[agent.py<br/>AI loop]
        L[mcp_link.py<br/>MCP client + pipe tap]
    end
    subgraph SERVER["MCP server (child process)"]
        S[server.py<br/>11 tools]
        T[tools/*.py<br/>logic]
    end
    D[(SQLite<br/>views + tables)]

    U -->|"question (HTTP POST)"| R
    R -->|"live log + approval dialog (SSE)"| U
    R --> A
    A <-->|"chat + tool list (HTTPS)"| G
    A --> L
    L <-->|"JSON-RPC over stdio<br/>every message logged"| S
    C <-->|"the same protocol"| S
    S --> T
    T -->|"read-only connection"| D
    T -->|"write connection<br/>place_order only"| D
```

- The **web host** is an MCP client. It starts the server as a child process and talks to it over stdio,
  the same way Claude Code and MCP Inspector do.
- Only the **server** touches the database. The host never opens it.
- **Groq** only decides which tool to call and writes the answer. Every fact comes from a tool result.

## 2. What happens when you ask a question

```mermaid
sequenceDiagram
    actor E as Employee
    participant P as Page
    participant H as Host
    participant G as Groq model
    participant S as MCP server
    participant D as SQLite

    E->>P: "Who are our top 5 customers?"
    P->>H: POST /api/ask
    H->>G: question + instructions + 11 tool descriptions
    G-->>H: call sales_summary(group_by=customer, limit=5)
    H->>S: tools/call sales_summary
    S->>D: SELECT ... FROM v_order_lines GROUP BY customer
    D-->>S: rows
    S-->>H: result (structured JSON)
    H->>G: tool result (compacted to columns + rows)
    G-->>H: final answer
    H-->>P: answer + tools used + token count
    Note over P,S: Every MCP message (→ and ←) also streams to the live log
```

- The model can loop: call a tool, read the result, call another (up to 8 model calls).
  "Who does Suyama report to, and what were his 2017 sales?" takes two tools.
- The **sums are done by SQL on the server**, not by the model adding up rows.

## 3. Placing an order: every way it can end

```mermaid
flowchart TD
    A[Model calls place_order] --> B{All checks pass?<br/>customer, employee, shipper,<br/>product exists, still sold, enough stock}
    B -->|no| R1[Refused with a code and a hint<br/>nobody is asked]
    B -->|yes| C{Can the client<br/>ask the user?}
    C -->|"no (no elicitation support)"| R2[Refused<br/>nothing written]
    C -->|yes| Q[Human sees the priced order:<br/>10 x Chai = 180.00, stock 39 to 29]
    Q --> E{Approve ticked?}
    E -->|"decline / cancel / unticked"| R3[declined<br/>nothing written]
    E -->|yes| T[One transaction:<br/>re-check stock, write order + lines,<br/>reduce stock, write audit row]
    T --> K{Stock still enough?}
    K -->|no| R4[Rolled back<br/>nothing written]
    K -->|yes| OK[Order placed<br/>shows in Recent changes]
    classDef stop fill:#FCEBEB,stroke:#A32D2D,color:#501313
    classDef done fill:#EAF3DE,stroke:#3B6D11,color:#173404
    class R1,R2,R3,R4 stop
    class OK done
```

- Red endings write nothing. Only the green path writes: all checks pass, a human approves, and the stock is still there.
- The approval is **not** a tool argument, so the model can't fill it in.

## 4. The approval, message by message (current spec, 2026-07-28)

```mermaid
sequenceDiagram
    actor E as Employee
    participant P as Page
    participant H as Host
    participant S as MCP server
    participant D as SQLite

    H->>S: tools/call place_order(ALFKI, Nancy, Speedy, [10 x Chai])
    S->>D: checks (read-only)
    S-->>H: result: input required, "Place this order? ... Total 180.00"
    H->>P: approval request (SSE)
    P->>E: dialog (focus starts on Decline)
    E->>P: clicks "Approve order"
    P->>H: POST /api/approvals/{id}
    H->>S: tools/call place_order again, with the answer (approve = true)
    S->>D: BEGIN IMMEDIATE ... COMMIT
    S-->>H: placed: order 11078, "No further confirmation is needed"
```

- In the current protocol, the server **answers the first call with a question** instead of a result.
  The client asks the human and **calls again with the answer**. Both calls appear in the live log.
- Older clients (protocol 2025-11-25, like MCP Inspector) get a separate `elicitation/create` request
  instead. The same server code handles both.

## 5. Getting through a long list: cursor paging

```mermaid
sequenceDiagram
    participant G as Model (via host)
    participant S as MCP server

    G->>S: list_orders(status=late)
    S-->>G: 20 orders, total_count 37, next_cursor "eyJv..."
    G->>S: list_orders(status=late, cursor "eyJv...")
    S-->>G: 17 orders, next_cursor null (last page)
    G->>S: list_orders(status=unshipped, cursor "eyJv...")
    S-->>G: error invalid_argument: cursor belongs to different filters
```

- The cursor is an opaque bookmark. Inside, it holds the offset plus a fingerprint of the filters,
  so it can't be reused on a different query.
- `total_count` tells the model how many results exist before it pages.

## 6. How the database is built

```mermaid
flowchart TD
    A[jpwhite3 Northwind SQLite<br/>16,282 orders] --> V1{SHA-256 matches<br/>the pinned file?}
    B[Microsoft instnwnd.sql<br/>original script] --> V2{SHA-256 matches?}
    V1 -->|no| X[Stop with an error]
    V2 -->|no| X
    V1 -->|yes| C[Keep orders 10248-11077 only<br/>drop 2 junk customers]
    V2 -->|yes| F[Read the 830 original<br/>freight values]
    F --> R[Restore freight on all 830 orders]
    C --> R
    R --> W[Create our SQL views<br/>and the audit_log table]
    W --> K{Checks: row counts, foreign keys,<br/>every freight value,<br/>total revenue = 1,265,793.04}
    K -->|fail| X
    K -->|pass| P[(northwind-clean.db<br/>pristine: tests + eval)]
    P --> Q[(northwind.db<br/>working copy: the server writes here)]
    classDef stop fill:#FCEBEB,stroke:#A32D2D,color:#501313
    classDef done fill:#EAF3DE,stroke:#3B6D11,color:#173404
    class X stop
    class P,Q done
```

- Both downloads are pinned to a commit and checked by hash, so the build gives the same result every time.
- The total revenue is the figure published for the original Northwind, which independently confirms the cleanup.

## 7. How the evaluation runs

```mermaid
flowchart TD
    Q[eval/questions.json<br/>14 questions, 159 expected facts] --> R[run_eval.py]
    R --> N[Copy the pristine database<br/>to a temp folder]
    N --> H[Start its own host<br/>auto-approval on, for this host only]
    H --> L{For each question}
    L --> ASK[POST /api/ask]
    ASK --> CHK{Expected tool called?<br/>Every fact in the answer?<br/>Database changed as expected?}
    CHK --> REP[eval/results/latest.md<br/>+ latest.json]
```

- The expected answers were computed with **raw SQL on the original tables**, not the server's views,
  so the eval checks the server independently.
- Facts are compared ignoring formatting (`$`, thousands commas, accents, curly quotes, special dashes),
  and numbers must match within 0.01.

## 8. The data model

```mermaid
erDiagram
    CUSTOMERS ||--o{ ORDERS : places
    EMPLOYEES ||--o{ ORDERS : sells
    SHIPPERS ||--o{ ORDERS : ships
    EMPLOYEES |o--o{ EMPLOYEES : "reports to"
    ORDERS ||--|{ ORDER_DETAILS : "has lines"
    PRODUCTS ||--o{ ORDER_DETAILS : "appears in"
    CATEGORIES ||--o{ PRODUCTS : groups
    SUPPLIERS ||--o{ PRODUCTS : supplies
    CUSTOMERS {
        text CustomerID PK
        text CompanyName
        text Country
    }
    ORDERS {
        int OrderID PK
        text CustomerID FK
        int EmployeeID FK
        int ShipVia FK
        date OrderDate
        date ShippedDate "null = not shipped"
        num Freight
    }
    ORDER_DETAILS {
        int OrderID PK
        int ProductID PK
        num UnitPrice "price paid"
        int Quantity
        real Discount
    }
    PRODUCTS {
        int ProductID PK
        text ProductName
        num UnitPrice "today's list price"
        int UnitsInStock
        text Discontinued
    }
    CATEGORIES {
        int CategoryID PK
        text CategoryName
    }
    SUPPLIERS {
        int SupplierID PK
        text CompanyName
    }
    EMPLOYEES {
        int EmployeeID PK
        text LastName
        int ReportsTo FK
    }
    SHIPPERS {
        int ShipperID PK
        text CompanyName
    }
```

- Order lines hold the **price actually paid**. In 658 lines it differs from today's list price,
  which is why revenue is always computed from the order lines.
