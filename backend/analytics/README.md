# Analytics

This folder contains query logging for understanding what visitors ask about.

## Files

- **analytics.py** - Logging functions (tracked in git)
- **queries.json** - Logged queries (gitignored for privacy)
- **.gitkeep** - Ensures folder structure is tracked

## Privacy

The `queries.json` file is gitignored and never committed. It stays local to protect user privacy.

## Usage

View recent queries:
```bash
# Last 20 queries
tail -20 backend/analytics/queries.json

# Total query count
wc -l backend/analytics/queries.json

# Most common questions (requires jq)
cat backend/analytics/queries.json | jq -r '.query' | sort | uniq -c | sort -rn | head -10
```

## Data Format

Each line is a JSON object:
```json
{"timestamp": "2026-01-25T10:30:00Z", "session_id": "abc123", "query": "What AI projects has Dakota built?", "response_preview": "Dakota has hands-on experience..."}
```
