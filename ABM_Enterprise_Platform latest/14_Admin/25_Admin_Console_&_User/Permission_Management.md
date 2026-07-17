# Module 25 — Admin Console & User/Permission Management

> **Domain folder:** `14_Admin`  
> **Replaces / equivalent to:** HubSpot settings + super-admin + billing/quotas + RBAC.

## 1. Purpose
The control plane: organizations/tenants, teams, users, roles & permissions (RBAC), API keys, domains, SMTP, integrations, branding, audit logs, usage, billing, quotas, AI credits, monitoring and health — everything an operator configures and governs, with full multi-tenancy.

## 2. Scope
**In scope**
- Tenant/org management (multi-tenancy)
- Users, teams, roles, granular permissions (RBAC)
- API keys, domains, SMTP, integrations, branding
- Usage, billing, quotas, AI credits, rate limits
- Audit logs (platform-wide), monitoring, health, feature flags

**Out of scope**
- Per-engine business config lives in each engine; Admin holds cross-cutting governance
- API routing (Gateway)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Tenant Owner/Admin | Governs the workspace |
| RevOps | Manages users/teams/permissions |
| Billing admin | Quotas/credits |

## 4. Data Entities & Schema

### `tenant`
An organization/workspace.

```
id UUID pk; name text; plan text; status enum(active,suspended); settings jsonb; created_at
```

### `user`
A user.

```
id UUID pk; tenant_id UUID; email citext; name text; status enum(active,invited,disabled); last_login_at
```

### `team`
A team.

```
id UUID pk; tenant_id UUID; name text; member_ids uuid[]
```

### `role`
A role with permissions.

```
id UUID pk; tenant_id UUID; name text; permissions text[]; is_system bool
```

### `quota`
Usage quota/credit.

```
id UUID pk; tenant_id UUID; kind enum(ai_credits,emails,api_calls,enrichment_credits,seats); limit int; used int; period text
```

### `audit_entry`
Platform audit.

```
id UUID pk; tenant_id UUID; actor_id UUID; area text; action text; detail jsonb; at timestamptz
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/admin/tenants` | Create/configure a tenant. | 201 |
| `POST` | `/v1/admin/users:invite` | Invite a user + role. | 201 |
| `POST` | `/v1/admin/roles` | Create a role with permissions. | 201 |
| `GET` | `/v1/admin/usage` | Usage/quota/credit dashboard. | 200 |
| `GET` | `/v1/admin/audit` | Platform audit log. | 200 |
| `GET` | `/v1/admin/health` | System health/monitoring. | 200 |

## 6. Core Workflows
1. Provision tenant -> configure branding/domains/SMTP -> invite users, assign roles/teams -> set quotas/credits -> monitor usage & health; permission changes take effect immediately across services
2. Quota exhaustion -> block relevant action + notify

## 7. State Machine — `tenant`
**States:** active, suspended

**Transitions:** active->suspended on billing/policy; back on resolve

## 8. Events
**Publishes:** `tenant.provisioned`, `user.invited`, `role.changed`, `quota.exhausted`

**Subscribes:** `* (usage metering from all engines)`

## 9. Business Rules
- **ADM-001:** Full multi-tenancy — every entity is tenant-scoped; no cross-tenant access ever.
- **ADM-002:** RBAC is deny-by-default; permissions are additive via roles.
- **ADM-003:** Quotas (AI credits, emails, enrichment, API) enforced; exhaustion blocks + alerts.
- **ADM-004:** Every privileged action is audited platform-wide.
- **ADM-005:** Row-level security ties records to owner/team; managers see team, admins see tenant.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `admin.full` | Admin/Owner |
| `users.manage` | RevOps, Admin |
| `billing.manage` | Billing admin, Admin |
| `audit.read` | Admin |

## 11. Validations
- email unique per tenant
- role permissions valid
- quota limits>=0

## 12. Error Scenarios
- 402 quota exceeded
- 403 cross-tenant attempt
- 409 duplicate user

## 13. Internal Integrations
All engines (RBAC + quotas), API Gateway (keys), Integration Layer (connectors), Notification

## 14. Testing Requirements
- Tenant isolation (no leakage)
- RBAC deny-by-default matrix
- Quota enforcement + block
- Audit completeness
- Row-level security

## 15. Acceptance Criteria
- [ ] Two tenants fully isolated
- [ ] Custom role limits a user to read-only CRM
- [ ] AI credit exhaustion blocks generation with clear error

## 16. Edge Cases
- User in multiple teams -> union of permissions
- Suspended tenant -> read-only/blocked gracefully
- Credit hits zero mid-journey -> pause + notify, no data loss

## 17. Implementation Checklist
- [ ] tenant/user/team/role tables + RBAC
- [ ] quota/credit metering
- [ ] branding/domain/SMTP config
- [ ] platform audit
- [ ] health/monitoring
- [ ] feature flags

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
