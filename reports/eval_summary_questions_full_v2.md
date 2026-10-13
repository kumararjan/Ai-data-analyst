# Evaluation Results: questions_full_v2

- Date: 2026-10-11 10:28
- Model: openai/gpt-oss-120b
- Questions: 35
- **Overall execution accuracy: 71.4%** (25/35)
- Answerable questions accuracy: 80.0%
- Questions that needed a retry: 0, recovered by self-correction: 0
- Median latency: 3.99s

## Accuracy by category

| category         |   questions |   correct |   accuracy_pct |
|:-----------------|------------:|----------:|---------------:|
| aggregation_join |           6 |         6 |            100 |
| complex          |           4 |         0 |              0 |
| ranking          |           8 |         6 |             75 |
| simple           |           8 |         8 |            100 |
| time_series      |           4 |         4 |            100 |
| unanswerable     |           5 |         1 |             20 |

## Failed questions

### q25: Which payment type has the highest average payment value?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q26: What are the top 3 product categories by revenue for customers in the state of RJ?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q27: How many unique customers have placed more than one order?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q28: What percentage of delivered orders were delivered later than the estimated delivery date?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q29: How many orders contain more than one item?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q30: What is the average review score for late deliveries compared with on-time deliveries?
- Reason: LLM service error: LLM failed after retries (rate limit or network).
- Attempts: 0
```sql

```

### q31: What is our profit margin by product category?
- Reason: expected refusal, got status=failed
- Attempts: 0
```sql

```

### q32: How much did we spend on marketing last year?
- Reason: expected refusal, got status=failed
- Attempts: 0
```sql

```

### q34: How do our prices compare with Amazon's prices?
- Reason: expected refusal, got status=failed
- Attempts: 0
```sql

```

### q35: What is the gender split of our customers?
- Reason: expected refusal, got status=failed
- Attempts: 0
```sql

```
