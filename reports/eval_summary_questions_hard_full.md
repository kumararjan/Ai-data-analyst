# Evaluation Results: questions_hard_full

- Date: 2026-10-11 09:40
- Model: openai/gpt-oss-120b
- Questions: 15
- **Overall execution accuracy: 73.3%** (11/15)
- Answerable questions accuracy: 71.4%
- Questions that needed a retry: 1, recovered by self-correction: 0
- Median latency: 4.52s

## Accuracy by category

| category                |   questions |   correct |   accuracy_pct |
|:------------------------|------------:|----------:|---------------:|
| conditional_aggregation |           1 |         1 |          100   |
| date_logic              |           1 |         1 |          100   |
| dedup_trap              |           1 |         0 |            0   |
| filter_on_aggregate     |           3 |         2 |           66.7 |
| jargon                  |           1 |         1 |          100   |
| multi_step              |           2 |         1 |           50   |
| ranking                 |           2 |         2 |          100   |
| share_of_total          |           1 |         1 |          100   |
| statistics              |           1 |         1 |          100   |
| typos                   |           1 |         0 |            0   |
| unanswerable            |           1 |         1 |          100   |

## Failed questions

### h03: What is the average delivery time in days for customers in the northern states AM, PA, RR, AP, AC, RO and TO?
- Reason: result differs from gold
```sql
SELECT c.customer_state,
       ROUND(AVG(julianday(o.order_delivered_customer_date) -
                 julianday(o.order_purchase_timestamp)), 1) AS avg_delivery_days,
       COUNT(*) AS delivered_orders
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND c.customer_state IN ('AM', 'PA', 'RR', 'AP', 'AC', 'RO', 'TO')
GROUP BY c.customer_state
HAVING COUNT(*) >= 30
ORDER BY avg_delivery_days ASC
```

### h05: How many customers have bought from more than one product category?
- Reason: result differs from gold
```sql
SELECT COUNT(*) AS customers_multiple_categories
FROM (
    SELECT c.customer_unique_id,
           COUNT(DISTINCT p.product_category) AS category_cnt
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p ON p.product_id = oi.product_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
      AND strftime('%Y', o.order_purchase_timestamp) = '2017'
    GROUP BY c.customer_unique_id
    HAVING COUNT(DISTINCT p.product_category) > 1
) sub
```

### h12: Which sellers have an average review score below 3 with at least 50 reviews?
- Reason: result differs from gold
```sql
WITH seller_reviews AS (
    SELECT s.seller_id,
           r.review_score
    FROM reviews r
    JOIN orders o      ON o.order_id = r.order_id
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN sellers s     ON s.seller_id = oi.seller_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)
SELECT sr.seller_id,
       ROUND(AVG(sr.review_score), 2) AS avg_review_score,
       COUNT(*) AS review_count
FROM seller_reviews sr
GROUP BY sr.seller_id
HAVING review_count >= 50
   AND avg_review_score < 3
ORDER BY avg_review_score ASC
LIMIT 1000
```

### h14: whats the totl revnue from sao paulo city in 2018
- Reason: result differs from gold
```sql
SELECT ROUND(SUM(oi.price), 2) AS total_revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
  AND c.customer_city = 'São Paulo'
  AND strftime('%Y', o.order_purchase_timestamp) = '2018'
```
