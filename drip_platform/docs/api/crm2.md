# CRM2 API — Custom Objects, CPQ Quotes, Property History

All routes are under `/crm` and inherit route-level authorization
(`SCOPE_POLICY: /crm → crm.read`) and per-request tenant scoping (RLS GUC set by
`get_db`). Money is always integer **minor units** (halalas/cents). Errors:
`422` = validation/domain error, `404` = entity not found. Full machine-readable
spec is served live at `/openapi.json` (and `/docs`).

## Custom Objects
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/crm/objects` | `{key,label,schema:[{key,type,required?,options?}]}` | Define a dynamic object type. `type ∈ text,number,date,bool,enum,ref`. 201. |
| GET | `/crm/objects` | — | List defined object types. |
| POST | `/crm/objects/{key}/records` | `{data:{...}}` | Create record; strict validation (required, enum, unknown-field reject). 201. |
| GET | `/crm/objects/{key}/records?limit=` | — | List records. |
| PATCH | `/crm/records/{record_id}` | `{data:{...}}` | Partial validated update. 404 if missing. |
| DELETE | `/crm/records/{record_id}` | — | 404 if missing. |

## Products / Price Books
| Method | Path | Body |
|---|---|---|
| POST | `/crm/products` | `{name,sku?,description?}` |
| POST | `/crm/price-books` | `{name,currency?,is_default?}` |
| POST | `/crm/price-books/{id}/prices` | `{product_id,unit_amount_minor,currency?}` |

## Quotes (CPQ)
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/crm/quotes` | `{name,org_id?,opportunity_id?,currency?}` | 201. |
| POST | `/crm/quotes/{id}/lines` | `{description,quantity,unit_amount_minor,product_id?}` | Ad-hoc line. |
| POST | `/crm/quotes/{id}/product-lines` | `{product_id,quantity,price_book_id}` | Priced from book; 422 if product not in book. |
| POST | `/crm/quotes/{id}/discount-tax` | `{discount_minor?,tax_minor?}` | Returns recomputed summary. |
| GET | `/crm/quotes/{id}` | — | `{subtotal,discount,tax,total,total_minor,lines}` formatted + minor. |

Totals recompute from line items on every mutation. Example: 3×`SAR 100,000` +
`SAR 50,000` onboarding − `SAR 10,000` discount → subtotal `SAR 350,000.00`,
total `SAR 340,000.00`.

## Property / Field History (audit-backed)
| Method | Path | Returns |
|---|---|---|
| GET | `/crm/records/{table}/{row_id}/history?limit=` | Full change timeline (who/when/action/changed/before/after). |
| GET | `/crm/records/{table}/{row_id}/history/{field}` | One field's value timeline (insert value + each `from`→`to`). |

## Verification
`tests/test_crm2_api.py` — 20/20 integration checks through the real FastAPI app
(status codes, 422 validation, 404, money-correct quote math, OpenAPI presence).
`tests/test_crm2.py` — 19/19 service-level checks (SQLite + PostgreSQL).
