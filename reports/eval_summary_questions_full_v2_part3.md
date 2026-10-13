# Evaluation Results: questions_full_v2_part3

- Date: 2026-10-11 13:32
- Model: openai/gpt-oss-120b
- Questions: 9
- **Overall execution accuracy: 33.3%** (3/9)
- Answerable questions accuracy: 60.0%
- Questions that needed a retry: 0, recovered by self-correction: 0
- Median latency: 0.18s

## Accuracy by category

| category     |   questions |   correct |   accuracy_pct |
|:-------------|------------:|----------:|---------------:|
| complex      |           4 |         2 |             50 |
| ranking      |           1 |         1 |            100 |
| unanswerable |           4 |         0 |              0 |

## Failed questions

### q29: How many orders contain more than one item?
- Reason: LLM service error: The free AI quota is used up for now (groq daily quota reached). Please try again later.
- Attempts: 0
```sql

```

### q30: What is the average review score for late deliveries compared with on-time deliveries?
- Reason: LLM service error: The free AI quota is used up for now (groq daily quota reached). Please try again later.
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
