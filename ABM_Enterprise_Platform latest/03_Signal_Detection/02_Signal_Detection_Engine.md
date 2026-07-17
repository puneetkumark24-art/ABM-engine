# Module 02 — Signal Detection Engine

> **Domain folder:** `03_Signal_Detection`  
> **Replaces / equivalent to:** 6sense/Bombora intent + Google Alerts + custom scrapers — capture & first-pass classification.

## 1. Purpose
Autonomous capture of buying and context signals across eight sourcing sub-streams, with provenance, idempotency, relevance filtering, dedup, and decay — producing clean, deduped, confidence-eligible signals for the Intelligence Engine.

## 2. Scope
**In scope**
- 8 capture sub-streams (NEWS/REG/EXEC/VENDOR/SUBS/EVENT/FIN/PATH)
- raw_captures provenance log + dedup
- SIG-RELEVANCE 4-axis filter
- Signal decay stamping
- Clustering related signals

**Out of scope**
- Deep reasoning (Intelligence Engine)
- Contact enrichment (Enrichment Engine)
- LinkedIn action-taking (LinkedIn Engine, 12)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| System | Runs streams on cadence |
| Data Steward | Tunes sources & relevance rules |
| BD/AE | Sees the filtered signal feed |

## 4. Data Entities & Schema

### `raw_capture`
Append-only provenance record of every fetch.

```
id UUID pk; tenant_id UUID; stream enum(news,reg,exec,vendor,subs,event,fin,path); source_url text; payload jsonb; dedup_hash text unique; fetched_at timestamptz
```

### `signal`
A promoted, relevant signal.

```
id UUID pk; tenant_id UUID; account_id UUID null; type enum(leadership,regulatory,product,hiring,funding,tender,partnership,event,financial); title text; summary text; urgency enum(P1,P2,P3,P4); relevance numeric(4,3); confidence numeric(4,3); source_reliability numeric(4,3); decay_category enum(fast,medium,slow); decay_expires_at timestamptz; cluster_id UUID null; raw_capture_id UUID fk; created_at timestamptz
```

### `signal_cluster`
Group of signals describing one underlying event.

```
id UUID pk; tenant_id UUID; account_id UUID; label text; signal_ids uuid[]; promoted bool; created_at
```

### `source`
A configured capture source.

```
id UUID pk; tenant_id UUID; stream enum; name text; url_or_query text; cadence_cron text; reliability numeric(4,3); enabled bool; ban_risk enum(none,low,high)
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/signals` | Filter feed by account/type/urgency/min-relevance/date. | 200 paged |
| `POST` | `/v1/signals` | Manual signal entry (a capture adapter). | 201 |
| `POST` | `/v1/signals/{id}:reclassify` | Override type/urgency; logged. | 200 |
| `GET` | `/v1/sources` | List configured sources. | 200 |
| `POST` | `/v1/sources` | Add/enable a source with cadence + ban-risk. | 201 |
| `POST` | `/v1/signals:ingest` | Internal ingest endpoint used by stream workers. | 202 |

## 6. Core Workflows
1. Worker fetches -> write raw_capture (dedup_hash) -> relevance filter (4 axes) -> if high: create signal + stamp decay -> cluster -> emit signal.created / signal.cluster.promoted
2. Ban-risk circuit breaker: high-risk stream (LinkedIn) throttles/halts on anomaly before capture

## 7. State Machine — `signal`
**States:** captured, filtered_out, active, expired, clustered

**Transitions:** captured->active on relevance pass; captured->filtered_out on low relevance (retained, not surfaced); active->expired at decay; active->clustered when joined to a cluster

## 8. Events
**Publishes:** `signal.created`, `signal.cluster.promoted`, `signal.filtered_out`, `source.ban_risk.tripped`

**Subscribes:** `schedule.tick`, `account.created (to seed watches)`

## 9. Business Rules
- **SIG-001:** Nothing becomes a signal without first existing as a raw_capture (provenance mandatory).
- **SIG-002:** dedup_hash collision => merge into existing signal, never create duplicate.
- **SIG-003:** Relevance <0.4 => filtered_out (retained, never surfaced to users).
- **SIG-004:** LinkedIn/SIG-PATH streams may not run until ban-risk circuit breaker service is healthy.
- **SIG-005:** Every signal carries decay_category; expired signals excluded from scoring reads.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `signals.read` | All roles |
| `signals.create` | AE, Steward, system |
| `sources.manage` | Steward, Admin |

## 11. Validations
- dedup_hash unique per tenant
- relevance/confidence in [0,1]
- cadence_cron valid

## 12. Error Scenarios
- 409 duplicate capture
- 422 invalid cron
- 503 stream disabled by circuit breaker

## 13. Internal Integrations
Intelligence Engine (clusters out), Account Engine (attribution), Scoring (signal strength dim), Enrichment (trigger on leadership/hiring)

## 14. Testing Requirements
- Idempotency: same payload twice -> one signal
- Relevance gate golden set
- Decay expiry excludes from scoring query
- Circuit breaker halts high-risk stream on simulated ban

## 15. Acceptance Criteria
- [ ] Re-running a scan never inflates counts
- [ ] Football-sponsorship vs RFP correctly separated by relevance
- [ ] Expired signals vanish from feed default view

## 16. Edge Cases
- Same event from 2 feeds -> single clustered signal
- Non-English (Arabic) source -> language-tagged, still filtered
- Source goes 404 -> disabled + steward notified, no crash

## 17. Implementation Checklist
- [ ] raw_captures + signals + clusters + sources tables
- [ ] 8 stream workers (NEWS live; others staged)
- [ ] relevance filter service
- [ ] dedup + decay
- [ ] circuit breaker
- [ ] feed API

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
