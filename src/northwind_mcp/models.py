"""Result shapes returned by the tools.

The SDK turns each model into the tool's `outputSchema`, and returns results as
`structuredContent` plus the same JSON as text (for clients that only read text).
Rule: every ID travels with its name, so the model never needs an extra call to
find out what an ID refers to. Money is rounded to 2 decimals.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Page(BaseModel):
    total_count: int = Field(description="How many results match in total, across all pages.")
    next_cursor: str | None = Field(
        description="Pass this as `cursor` to get the next page. null means this is the last page."
    )


class CustomerSummary(BaseModel):
    customer_id: str
    customer_name: str
    contact_name: str | None
    city: str | None
    country: str | None
    order_count: int
    revenue: float = Field(description="Total revenue from this customer (price paid x quantity x (1 - discount)).")
    last_order_date: str | None = Field(description="null if the customer has never ordered.")


class CustomerSearchResult(Page):
    customers: list[CustomerSummary]


class RecentOrder(BaseModel):
    order_id: int
    order_date: str
    status: str
    revenue: float


class CustomerDetail(BaseModel):
    customer_id: str
    customer_name: str
    contact_name: str | None
    contact_title: str | None
    phone: str | None
    city: str | None
    country: str | None
    order_count: int
    revenue: float = Field(description="Total revenue from this customer (price paid x quantity x (1 - discount)).")
    first_order_date: str | None
    last_order_date: str | None
    recent_orders: list[RecentOrder] = Field(description="The 5 most recent orders, newest first.")
