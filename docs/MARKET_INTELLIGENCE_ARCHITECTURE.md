# Market Intelligence Architecture

## Objective

Build an auditable, point-in-time market intelligence sidecar for the existing
NFI dry-run system. External data may produce factors, regime labels, and
shadow-only stake multipliers. It never modifies the NFI strategy or submits
orders.

## Flow

```text
read-only providers -> append-only raw store -> normalized event store
-> factor store -> confidence-aware scores -> regime and shadow sizing
-> ablation / walk-forward / forward evidence -> Gatekeeper
```

## Safety Boundaries

- Main runtime remains dry-run, spot-only, credential-free, and localhost-only.
- Provider credentials come from process environment variables only.
- Request URLs, reports, logs, raw payloads, and Git never contain credentials.
- Community, social, and ordinary sentiment cannot hard block an NFI signal.
- Only a critical event, critical data failure, or critical liquidity failure
  may propose a `0.0` shadow multiplier.
- No candidate can progress beyond a shadow proposal.

## Point-in-time Contract

Every normalized record carries `event_time`, `available_time`, `collected_at`,
and `revised_at`. Historical provider responses are not assumed to be
point-in-time safe. A factor is eligible for historical evaluation only when
its `available_time` is no later than the simulated decision time.

Raw responses are append-only gzip JSON with hashes. Normalized and factor
records are append-only JSONL. Manifests retain source, request, trace, schema,
hash, and quality metadata.

## Degradation

Provider failures are isolated. Missing keyed providers reduce source coverage
and data confidence; their weights are redistributed only across available
factor groups. Missing values are never treated as zero. Low confidence shrinks
scores toward neutral using:

```text
effective_score = 50 + confidence * (raw_score - 50)
```

## Acceptance Criteria

- Required public providers can produce a current snapshot or a precise network error.
- Keyed providers report `KEY_MISSING` without exposing key values.
- Point-in-time schema, deduplication, confidence shrinkage, missing-source
  reweighting, stale behavior, shadow-only promotion, and no-live boundaries
  have executable tests.
- New factor history is marked insufficient until real snapshots accumulate;
  no synthetic profitability claim is allowed.
