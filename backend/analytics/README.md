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
{"timestamp": "2026-01-25T10:30:00Z", "session_id": "abc123", "query": "What AI projects has Dakota built?", "response_preview": "Dakota has hands-on experience..."}
```
