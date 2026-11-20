-- Our own views over the cleaned Northwind data.
-- They are the single place where joins and business rules live; the MCP tools
-- only filter, sort and page these views. Applied by scripts/build_db.py.
--
-- Rules defined here:
--   * Revenue of a line = line UnitPrice * Quantity * (1 - Discount).
--     Always the price actually paid (Order Details), never Products.UnitPrice:
--     658 lines were sold at a different price from today's list price.
--     Freight is not revenue.
--   * An order is "late" when it shipped after its RequiredDate.
--   * A product "needs reordering" when it is still sold (not discontinued) and
--     UnitsInStock + UnitsOnOrder <= ReorderLevel, i.e. even counting stock
--     already on order from the supplier, it is at or below its reorder level.

DROP VIEW IF EXISTS v_order_lines;
DROP VIEW IF EXISTS v_orders;
DROP VIEW IF EXISTS v_products;
DROP VIEW IF EXISTS v_customers;

-- One row per order line, with every linked name already joined.
CREATE VIEW v_order_lines AS
SELECT
    d.OrderID                                   AS order_id,
    o.OrderDate                                 AS order_date,
    o.CustomerID                                AS customer_id,
    c.CompanyName                               AS customer_name,
    o.ShipCountry                               AS ship_country,
    o.EmployeeID                                AS employee_id,
    e.FirstName || ' ' || e.LastName            AS employee_name,
    o.ShipVia                                   AS shipper_id,
    s.CompanyName                               AS shipper_name,
    d.ProductID                                 AS product_id,
    p.ProductName                               AS product_name,
    p.CategoryID                                AS category_id,
    cat.CategoryName                            AS category_name,
    p.SupplierID                                AS supplier_id,
    sup.CompanyName                             AS supplier_name,
    CAST(d.UnitPrice AS REAL)                   AS unit_price,
    d.Quantity                                  AS quantity,
    d.Discount                                  AS discount,
    d.UnitPrice * d.Quantity * (1 - d.Discount) AS revenue
FROM [Order Details] d
JOIN Orders o          ON o.OrderID = d.OrderID
JOIN Products p        ON p.ProductID = d.ProductID
LEFT JOIN Customers c  ON c.CustomerID = o.CustomerID
LEFT JOIN Employees e  ON e.EmployeeID = o.EmployeeID
LEFT JOIN Shippers s   ON s.ShipperID = o.ShipVia
LEFT JOIN Categories cat ON cat.CategoryID = p.CategoryID
LEFT JOIN Suppliers sup  ON sup.SupplierID = p.SupplierID;

-- One row per order: header, linked names, totals and status.
CREATE VIEW v_orders AS
SELECT
    o.OrderID                                   AS order_id,
    o.OrderDate                                 AS order_date,
    o.RequiredDate                              AS required_date,
    o.ShippedDate                               AS shipped_date,
    CASE WHEN o.ShippedDate IS NULL THEN 'unshipped' ELSE 'shipped' END AS status,
    CASE WHEN o.ShippedDate > o.RequiredDate THEN 1 ELSE 0 END          AS is_late,
    o.CustomerID                                AS customer_id,
    c.CompanyName                               AS customer_name,
    o.EmployeeID                                AS employee_id,
    e.FirstName || ' ' || e.LastName            AS employee_name,
    o.ShipVia                                   AS shipper_id,
    s.CompanyName                               AS shipper_name,
    CAST(o.Freight AS REAL)                     AS freight,
    o.ShipName                                  AS ship_name,
    o.ShipCity                                  AS ship_city,
    o.ShipCountry                               AS ship_country,
    (SELECT COUNT(*) FROM [Order Details] d WHERE d.OrderID = o.OrderID) AS line_count,
    (SELECT COALESCE(SUM(d.UnitPrice * d.Quantity * (1 - d.Discount)), 0)
       FROM [Order Details] d WHERE d.OrderID = o.OrderID)               AS revenue
FROM Orders o
LEFT JOIN Customers c ON c.CustomerID = o.CustomerID
LEFT JOIN Employees e ON e.EmployeeID = o.EmployeeID
LEFT JOIN Shippers s  ON s.ShipperID = o.ShipVia;

-- One row per product, with supplier, category and a stock status.
CREATE VIEW v_products AS
SELECT
    p.ProductID                                 AS product_id,
    p.ProductName                               AS product_name,
    p.CategoryID                                AS category_id,
    cat.CategoryName                            AS category_name,
    p.SupplierID                                AS supplier_id,
    sup.CompanyName                             AS supplier_name,
    sup.Country                                 AS supplier_country,
    p.QuantityPerUnit                           AS quantity_per_unit,
    CAST(p.UnitPrice AS REAL)                   AS list_price,
    p.UnitsInStock                              AS units_in_stock,
    p.UnitsOnOrder                              AS units_on_order,
    p.ReorderLevel                              AS reorder_level,
    CAST(p.Discontinued AS INTEGER)             AS discontinued,
    CASE
        WHEN p.UnitsInStock = 0 THEN 'out_of_stock'
        WHEN CAST(p.Discontinued AS INTEGER) = 0
             AND p.UnitsInStock + p.UnitsOnOrder <= p.ReorderLevel THEN 'reorder_needed'
        ELSE 'in_stock'
    END                                         AS stock_status
FROM Products p
LEFT JOIN Categories cat ON cat.CategoryID = p.CategoryID
LEFT JOIN Suppliers sup  ON sup.SupplierID = p.SupplierID;

-- One row per customer, INCLUDING customers who never ordered (LEFT JOIN).
CREATE VIEW v_customers AS
SELECT
    c.CustomerID                                AS customer_id,
    c.CompanyName                               AS customer_name,
    c.ContactName                               AS contact_name,
    c.ContactTitle                              AS contact_title,
    c.City                                      AS city,
    c.Country                                   AS country,
    c.Phone                                     AS phone,
    COUNT(o.order_id)                           AS order_count,
    COALESCE(SUM(o.revenue), 0)                 AS revenue,
    MIN(o.order_date)                           AS first_order_date,
    MAX(o.order_date)                           AS last_order_date
FROM Customers c
LEFT JOIN v_orders o ON o.customer_id = c.CustomerID
GROUP BY c.CustomerID;
