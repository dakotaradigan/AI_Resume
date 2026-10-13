# Analytics

This folder contains query logging for understanding what visitors ask about.

## Files

- **analytics.py** - Logging functions (tracked in git)
- **queries.jsonl** - Logged queries (gitignored for privacy)
- **feedback.jsonl** - User feedback ratings (gitignored for privacy)
- **.gitkeep** - Ensures folder structure is tracked

## Privacy

The `.jsonl` data files are gitignored and never committed. They stay local to protect user privacy.

## Usage

View recent queries:
```bash
# Last 20 queries
tail -20 backend/analytics/queries.jsonl

# Total query count
wc -l backend/analytics/queries.jsonl

# Most common questions (requires jq)
cat backend/analytics/queries.jsonl | jq -r '.query' | sort | uniq -c | sort -rn | head -10
```

## Data Format

Each line is a JSON object (JSONL format):
```json
{"timestamp": "2026-01-25T10:30:00Z", "session_id": "abc123", "query": "What AI projects has Dakota built?", "response": "Dakota has hands-on experience...", "model": "claude-sonnet-5", "route_reason": "simple", "usage": {"input_tokens": 120, "output_tokens": 40, "cache_read_input_tokens": 3900, "cache_creation_input_tokens": 0}, "cost_usd": 0.00142}
```

`session_id` is an HMAC of the live id, never the id itself. `model`,
`route_reason`, `usage` and `cost_usd` are present when a model generated
the reply (starter-cache hits have none). `cost_usd` is a list-price
estimate from `app.llm.estimate_cost_usd`, for cost-per-route analysis,
not billing truth.

Spend per model over the log (requires jq):
```bash
jq -r 'select(.cost_usd) | [.model, .cost_usd] | @tsv' backend/analytics/queries.jsonl \
  | awk '{sum[$1] += $2; n[$1]++} END {for (m in sum) printf "%s\t%d turns\t$%.4f\n", m, n[m], sum[m]}'
```
