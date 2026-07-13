# Market Intelligence Data Dictionary

## Point-in-time Record

| Field | Meaning |
|---|---|
| `source_id`, `provider` | Source registry identity and adapter |
| `asset`, `metric` | Canonical asset and factor name |
| `event_time` | When the underlying event occurred |
| `available_time` | Earliest time the system could observe it |
| `collected_at` | Local ingestion time |
| `revised_at` | Provider revision time when known |
| `raw_value`, `normalized_value`, `unit` | Value contract |
| `confidence`, `quality_flags` | Per-record quality evidence |
| `source_hash`, `request_id`, `trace_id` | Lineage and deduplication |
| `is_historical_backfill`, `point_in_time_safe` | Backtest eligibility controls |

## Score Families

Global scores keep risk appetite, social sentiment, crowding, news risk,
onchain, macro, liquidity, derivatives risk, and data confidence separate.
Per-asset scores keep sentiment, attention, crowding, news risk, relative
strength, liquidity, and quality separate.

Missing factor groups remain `null`; they are never converted to zero.
