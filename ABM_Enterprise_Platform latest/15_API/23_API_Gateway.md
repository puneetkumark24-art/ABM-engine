# Module 23 — API Gateway

> **Domain folder:** `15_API`  
> **Replaces / equivalent to:** Kong/Apigee + HubSpot public API surface.

## 1. Purpose
The single, secured entry point for all external and inter-service API traffic: routing, authentication, authorization, rate limiting, quotas, versioning, request/response validation, API keys, webhooks-out and developer docs — the front door to the whole platform.

## 2. Scope
**In scope**
- Request routing to services
- AuthN (OAuth2/JWT/API key) + AuthZ (RBAC/scopes)
- Rate limiting, quotas, throttling per tenant/key
- API versioning + deprecation
- Request/response validation (OpenAPI)
- Outbound webhooks + signing
- Developer portal / API docs

**Out of scope**
- Business logic (each engine)
- Identity store (Admin/User Mgmt)
- Event bus internals (Integration Layer)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| External developer | Uses the API |
| Admin | Manages keys/quotas |
| System | Inter-service calls |

## 4. Data Entities & Schema

### `api_key`
An API key/credential.

```
id UUID pk; tenant_id UUID; name text; hashed_key text; scopes text[]; rate_limit int; quota_month int; status enum(active,revoked); created_at; last_used_at
```

### `route`
A registered API route.

```
id text pk; path text; method text; service text; version text; auth_required bool; scopes text[]; deprecated bool
```

### `webhook_out`
Outbound webhook subscription.

```
id UUID pk; tenant_id UUID; event_types text[]; url text; secret text; status enum(active,paused); failures int
```

### `rate_bucket`
Per-key rate state.

```
key_id UUID pk; window_start timestamptz; count int
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/admin/api-keys` | Create/rotate an API key with scopes. | 201 |
| `GET` | `/v1/meta/openapi` | OpenAPI spec (all versions). | 200 |
| `POST` | `/v1/admin/webhooks` | Register an outbound webhook. | 201 |
| `GET` | `/v1/admin/usage` | API usage/quota per key. | 200 |

## 6. Core Workflows
1. Request -> gateway authenticates (key/JWT) -> authorizes scopes/RBAC -> rate-limit/quota check -> validate against OpenAPI -> route to service -> response validated/logged
2. Outbound: platform event -> matching webhook_out -> signed POST -> retry/backoff on failure -> pause after threshold

## 7. State Machine — `api_key`
**States:** active, revoked

**Transitions:** active->revoked on rotate/compromise

## 8. Events
**Publishes:** `api.key.created`, `api.webhook.failed`, `api.ratelimit.exceeded`

**Subscribes:** `* (for outbound webhooks)`

## 9. Business Rules
- **GW-001:** All external traffic authenticated + authorized; no anonymous business endpoints.
- **GW-002:** Rate limits & monthly quotas enforced per key/tenant; 429 on exceed.
- **GW-003:** Requests validated against OpenAPI; invalid -> 422 before hitting services.
- **GW-004:** Outbound webhooks are signed; consumers verify signature; failing endpoints auto-paused.
- **GW-005:** Deprecated versions return sunset headers; removed after policy window.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `apikeys.manage` | Admin |
| `gateway.config` | Admin |
| `usage.read` | Admin, tenant owner |

## 11. Validations
- scopes valid
- url https for webhooks
- version supported

## 12. Error Scenarios
- 401 bad key
- 403 scope denied
- 429 rate/quota
- 422 schema invalid

## 13. Internal Integrations
All engines (routing), User/Permission (RBAC), Integration Layer, Audit

## 14. Testing Requirements
- AuthN/Z matrix
- Rate-limit/quota enforcement
- OpenAPI validation rejects bad payloads
- Webhook signing + retry/pause

## 15. Acceptance Criteria
- [ ] External key with limited scopes can call only permitted endpoints, throttled at limit
- [ ] Outbound webhook delivers signed events with retry

## 16. Edge Cases
- Clock skew on JWT -> small leeway
- Burst above limit -> 429 + Retry-After
- Webhook endpoint flapping -> auto-pause + alert

## 17. Implementation Checklist
- [ ] gateway (routing/auth/limits)
- [ ] api key store + scopes
- [ ] OpenAPI validation
- [ ] outbound webhook dispatcher + signing
- [ ] developer portal
- [ ] usage metering

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
