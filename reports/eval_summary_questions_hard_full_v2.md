# Evaluation Results: questions_hard_full_v2

- Date: 2026-10-11 10:02
- Model: openai/gpt-oss-120b
- Questions: 15
- **Overall execution accuracy: 93.3%** (14/15)
- Answerable questions accuracy: 92.9%
- Questions that needed a retry: 0, recovered by self-correction: 0
- Median latency: 4.39s

## Accuracy by category

| category                |   questions |   correct |   accuracy_pct |
|:------------------------|------------:|----------:|---------------:|
| conditional_aggregation |           1 |         1 |            100 |
| date_logic              |           1 |         1 |            100 |
| dedup_trap              |           1 |         1 |            100 |
| filter_on_aggregate     |           3 |         3 |            100 |
| jargon                  |           1 |         1 |            100 |
| multi_step              |           2 |         1 |             50 |
| ranking                 |           2 |         2 |            100 |
| share_of_total          |           1 |         1 |            100 |
| statistics              |           1 |         1 |            100 |
| typos                   |           1 |         1 |            100 |
| unanswerable            |           1 |         1 |            100 |

## Failed questions

### h10: What percentage of orders were paid with more than one payment method?
- Reason: result differs from gold
- Attempts: 1
```sql
WITH valid_orders AS (
    SELECT o.order_id
    FROM orders o
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
),
payment_counts AS (
    SELECT po.order_id,
           COUNT(DISTINCT p.payment_type) AS payment_method_cnt
    FROM valid_orders po
    JOIN payments p ON p.order_id = po.order_id
    GROUP BY po.order_id
)
SELECT ROUND(100.0 * SUM(CASE WHEN payment_method_cnt > 1 THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS pct_multi_payment_orders
FROM payment_counts
```
