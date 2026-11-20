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


class InactiveCustomer(BaseModel):
    customer_id: str
    customer_name: str
    country: str | None
    order_count: int
    last_order_date: str | None = Field(description="null means the customer has never ordered.")


class InactiveCustomersResult(Page):
    since: str = Field(description="Customers with no order on or after this date are listed.")
    never_ordered_count: int = Field(description="How many of the matches have never placed any order.")
    customers: list[InactiveCustomer]


# --- Products ---------------------------------------------------------------


class ProductSummary(BaseModel):
    product_id: int
    product_name: str
    category_id: int
    category_name: str
    supplier_id: int
    supplier_name: str
    list_price: float = Field(description="Today's list price. Past orders may have been sold at other prices.")
    units_in_stock: int
    units_on_order: int = Field(description="Units already ordered from the supplier and on their way.")
    reorder_level: int
    discontinued: bool
    stock_status: str = Field(
        description="out_of_stock (0 in stock), reorder_needed (still sold and stock + units on order "
        "<= reorder level), or in_stock."
    )


class ProductSearchResult(Page):
    products: list[ProductSummary]


class ProductDetail(ProductSummary):
    supplier_country: str | None
    quantity_per_unit: str | None
    units_sold: int
    revenue: float
    order_count: int
    first_sold_date: str | None
    last_sold_date: str | None


# --- Orders -----------------------------------------------------------------


class OrderSummary(BaseModel):
    order_id: int
    order_date: str
    required_date: str
    shipped_date: str | None = Field(description="null means the order has not shipped yet.")
    status: str = Field(description="shipped or unshipped.")
    is_late: bool = Field(description="true when the order shipped after its required date.")
    customer_id: str
    customer_name: str
    employee_id: int
    employee_name: str
    shipper_id: int
    shipper_name: str
    line_count: int
    revenue: float
    freight: float


class OrderListResult(Page):
    orders: list[OrderSummary]


class OrderLine(BaseModel):
    product_id: int
    product_name: str
    unit_price: float = Field(description="The price actually paid on this order.")
    quantity: int
    discount: float = Field(description="Fraction, e.g. 0.15 = 15% off.")
    revenue: float


class OrderDetail(OrderSummary):
    ship_name: str | None
    ship_city: str | None
    ship_country: str | None
    lines: list[OrderLine]
    total_with_freight: float


# --- Reports ----------------------------------------------------------------


class SalesGroup(BaseModel):
    key: str = Field(description="The group's ID (or the month/year/country itself).")
    name: str
    revenue: float
    order_count: int
    units: int
    freight: float | None = Field(
        description="Freight of the orders in this group. null when grouping or filtering by product or "
        "category, because freight is charged per order, not per product."
    )


class SalesSummaryResult(Page):
    group_by: str
    metric: str
    total_revenue: float = Field(description="Revenue across all groups that match the filters.")
    groups: list[SalesGroup]


class ReferenceItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    country: str | None = None
    title: str | None = Field(default=None, description="Employees only: job title.")
    reports_to_id: int | None = Field(default=None, description="Employees only: their manager's ID.")
    reports_to_name: str | None = Field(default=None, description="Employees only: their manager's name.")
    phone: str | None = None


class ReferenceResult(BaseModel):
    kind: str
    items: list[ReferenceItem]
