# Evaluation Results: questions_baseline

- Date: 2026-10-11 09:49
- Model: openai/gpt-oss-120b
- Questions: 35
- **Overall execution accuracy: 68.6%** (24/35)
- Answerable questions accuracy: 66.7%
- Questions that needed a retry: 0, recovered by self-correction: 0
- Median latency: 0.95s

## Accuracy by category

| category         |   questions |   correct |   accuracy_pct |
|:-----------------|------------:|----------:|---------------:|
| aggregation_join |           6 |         0 |              0 |
| complex          |           4 |         2 |             50 |
| ranking          |           8 |         8 |            100 |
| simple           |           8 |         8 |            100 |
| time_series      |           4 |         2 |             50 |
| unanswerable     |           5 |         4 |             80 |

## Failed questions

### q09: What was the total revenue in 2017?
- Reason: result differs from gold
```sql
SELECT 
    SUM(p.payment_value) AS total_revenue_2017
FROM 
    orders o
JOIN 
    payments p
    ON o.order_id = p.order_id
WHERE 
    strftime('%Y', o.order_purchase_timestamp) = '2017'
```

### q10: What was the average order value in 2018?
- Reason: result differs from gold
```sql
SELECT AVG(order_total) AS average_order_value_2018
FROM (
    SELECT o.order_id, SUM(p.payment_value) AS order_total
    FROM orders o
    JOIN payments p ON o.order_id = p.order_id
    WHERE substr(o.order_purchase_timestamp, 1, 4) = '2018'
    GROUP BY o.order_id
)
```

### q11: How many units were sold in the health_beauty category?
- Reason: result differs from gold
```sql
SELECT COUNT(*) AS units_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
WHERE p.product_category = 'health_beauty'
```

### q12: What is the total freight cost for orders from customers in the state of SP?
- Reason: result differs from gold
```sql
SELECT SUM(oi.freight_value) AS total_freight_sp
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE c.customer_state = 'SP'
```

### q13: What is the total payment value for each payment type?
- Reason: result differs from gold
```sql
SELECT
    payment_type,
    SUM(payment_value) AS total_payment_value
FROM payments
GROUP BY payment_type
ORDER BY total_payment_value DESC
```

### q14: What is the average item price in the computers_accessories category?
- Reason: result differs from gold
```sql
SELECT AVG(oi.price) AS average_item_price
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
WHERE p.product_category = 'computers_accessories'
```

### q15: How many orders were placed each year?
- Reason: result differs from gold
```sql
SELECT 
    strftime('%Y', order_purchase_timestamp) AS year,
    COUNT(*) AS orders_count
FROM orders
GROUP BY year
ORDER BY year
```

### q18: How many orders were placed in each hour of the day?
- Reason: result differs from gold
```sql
SELECT 
    strftime('%H', order_purchase_timestamp) AS purchase_hour,
    COUNT(*) AS orders_count
FROM orders
GROUP BY purchase_hour
ORDER BY purchase_hour
```

### q27: How many unique customers have placed more than one order?
- Reason: result differs from gold
```sql
SELECT COUNT(*) AS unique_customers_multiple_orders
FROM (
    SELECT customer_id
    FROM orders
    GROUP BY customer_id
    HAVING COUNT(DISTINCT order_id) > 1
) AS sub
```

### q29: How many orders contain more than one item?
- Reason: result differs from gold
```sql
SELECT COUNT(*) AS orders_with_multiple_items
FROM (
    SELECT order_id
    FROM order_items
    GROUP BY order_id
    HAVING COUNT(*) > 1
) AS multi_item_orders
```

### q31: What is our profit margin by product category?
- Reason: expected refusal, got status=ok
```sql
SELECT
    p.product_category,
    ROUND(
        (SUM(pay.payment_value) - SUM(oi.price + oi.freight_value))
        / NULLIF(SUM(pay.payment_value), 0)
    , 4) AS profit_margin
FROM order_items AS oi
JOIN payments AS pay
    ON oi.order_id = pay.order_id
JOIN products AS p
    ON oi.product_id = p.product_id
GROUP BY p.product_category
ORDER BY profit_margin DESC
```
