# Module 14 — Asset Library

> **Domain folder:** `07_Marketing_Automation`  
> **Replaces / equivalent to:** HubSpot Files + DAM — content & collateral store.

## 1. Purpose
Central store for marketing/sales collateral (whitepapers, case studies, one-pagers, decks, images) with versioning, gating, usage tracking and CDN delivery — the source of truth for every asset a campaign, landing page or email references.

## 2. Scope
**In scope**
- Asset upload + versioning + metadata/tags
- Gating flag + signed/expiring links
- Usage tracking (downloads, which campaigns use it)
- CDN/hosting + access control
- AI-generated asset intake (proposals/case studies from AI Engine)

**Out of scope**
- Generation (AI Engine)
- Page building (Landing Engine)
- Email templates (Marketing Engine)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketer | Manages collateral |
| AE | Attaches assets to outreach |
| System | Stores AI-generated assets |

## 4. Data Entities & Schema

### `asset`
A stored asset.

```
id UUID pk; tenant_id UUID; name text; type enum(whitepaper,case_study,one_pager,deck,image,pdf,doc,other); storage_url text; gated bool; tags text[]; version int; owner_id UUID; created_at
```

### `asset_usage`
Where/when used.

```
id UUID pk; asset_id UUID; context_type enum(campaign,landing,email,linkedin); context_id UUID; downloads int; last_used_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/assets` | Upload/register asset (versioned). | 201 |
| `GET` | `/v1/assets` | Search/filter by type/tag. | 200 |
| `POST` | `/v1/assets/{id}:sign` | Get a signed expiring download link. | 200 |
| `GET` | `/v1/assets/{id}/usage` | Usage & download analytics. | 200 |

## 6. Core Workflows
1. Upload -> virus/type check -> version -> CDN publish -> available to campaigns/pages/emails; gated assets served via signed links from Landing/Email
2. AI Engine outputs proposal/case study -> stored as asset version

## 7. State Machine — `asset`
**States:** draft, published, archived

**Transitions:** draft->published on publish; new upload => version++; ->archived

## 8. Events
**Publishes:** `asset.published`, `asset.downloaded`

**Subscribes:** `ai.generation.approved (store output)`, `form.submitted (gated download)`

## 9. Business Rules
- **AST-001:** Gated assets only served via signed, expiring links (no public URL).
- **AST-002:** New upload creates a new version; old versions retained & referenceable.
- **AST-003:** Download events feed engagement + campaign analytics.
- **AST-004:** File type/size validated; malware-scanned before publish.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `assets.manage` | Marketer, Admin |
| `assets.read` | All |

## 11. Validations
- allowed type/size
- unique name+version
- signed link TTL set

## 12. Error Scenarios
- 415 unsupported type
- 413 too large
- 410 expired link

## 13. Internal Integrations
Landing/Forms (gating), Marketing/Email (attach), AI Engine (store outputs), Analytics (downloads)

## 14. Testing Requirements
- Version increments correctly
- Signed link expiry
- Malware scan gate
- Usage tracking accuracy

## 15. Acceptance Criteria
- [ ] Upload a case study, gate it, serve via expiring link, track downloads
- [ ] New version supersedes but keeps old

## 16. Edge Cases
- Same asset used in 3 campaigns -> usage attributed to each
- Expired link re-request after new submission -> fresh link
- Archived asset referenced by live page -> warn before archive

## 17. Implementation Checklist
- [ ] asset + usage tables
- [ ] upload + versioning + scan
- [ ] CDN + signed links
- [ ] usage tracker

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
