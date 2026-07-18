# DRIP — Deployment Playbook

Two paths. Path A gets you a public URL in ~30 minutes with zero DevOps. Path B
is the enterprise KSA-residency path using the Terraform we built in Sprint 1.
Start with A; move to B when the bank-compliance conversation demands it.

## Pre-deploy checklist (both paths)

1. **Secrets** — set these environment variables on the host (never in code):
   - `DATABASE_URL` — the cloud Postgres URL
   - `JWT_SECRET` — long random string (e.g. 64 hex chars)
   - `AUTH_ENFORCED=true`
   - `ADMIN_EMAIL` / `ADMIN_PASSWORD` — your login for /auth/login
   - `CORS_ORIGINS=https://drip-saudi-abm.lovable.app` (+ any other UI origins)
   - optional: `GA4_MEASUREMENT_ID`, `GA4_API_SECRET`, `FIELD_ENCRYPTION_KEY`
2. **Migrate the cloud DB**: `python -m alembic upgrade head` against the cloud
   `DATABASE_URL` (fresh DB → full 28-revision chain applies cleanly).
3. **Move your data** (8k contacts) from local Postgres to cloud:
   ```cmd
   pg_dump -h localhost -U postgres -d drip -F c -f drip_backup.dump
   pg_restore -d "<CLOUD_DATABASE_URL>" --no-owner --no-privileges drip_backup.dump
   python sync_db.py   (with DATABASE_URL set to the cloud URL — belt & braces)
   ```
4. **Email stays dry-run** until SES creds exist — nothing can send by accident.

## Path A — Railway or Render (fastest public URL)

Both auto-detect the `deploy/Dockerfile`, provide managed Postgres, TLS, and a
public URL. Steps (Railway shown; Render is equivalent):

1. Push the repo to GitHub (private repo is fine):
   ```cmd
   cd "C:\Users\Puneet\Desktop\ABM business logic\drip_platform"
   git init & git add -A & git commit -m "DRIP platform"
   ```
   then create a private repo on github.com and `git remote add origin ... && git push -u origin main`.
2. railway.app → New Project → **Deploy from GitHub repo** → select the repo.
   Set root Dockerfile path to `deploy/Dockerfile` if asked.
3. Add a **PostgreSQL** service in the same project; Railway injects
   `DATABASE_URL` automatically (convert to `postgresql+psycopg2://` prefix in
   a variable override if needed).
4. Set the env vars from the checklist in the service's Variables tab.
5. Deploy → note the public URL (e.g. `https://drip-api.up.railway.app`).
6. Run migrations once (Railway shell or locally against the cloud URL):
   `python -m alembic upgrade head`, then restore your dump (checklist step 3).
7. Smoke test: `https://<url>/health/ready`, `/app` (sign in), `/docs`.

Cost: ~$5–20/month. Caveat: regions are US/EU — fine for a pilot, but KSA
banking-data residency (PDPL) eventually wants Path B.

## Path B — AWS me-south-1 (Bahrain) via the Sprint-1 Terraform

KSA-adjacent residency, managed multi-AZ Postgres with PITR, EKS, Redis.

1. Prereqs: AWS account, `aws configure` with an IAM admin key, Terraform CLI.
2. ```bash
   cd deploy/terraform
   terraform init
   terraform apply        # provisions RDS Postgres 16, Redis, EKS in me-south-1
   ```
3. Build & push the image (ECR), then:
   ```bash
   kubectl apply -f deploy/k8s/drip.yaml   # api x3, worker+HPA, scheduler
   ```
   Secrets go into the K8s Secret in that manifest (JWT, DB URL, admin login).
4. Point a domain (e.g. `api.drip.decimaltech.sa`) at the load balancer; TLS
   via ACM. Restore data as in the checklist.
5. Monitoring: `deploy/observability/alerts.yml` into your Prometheus stack;
   runbooks in `docs/runbooks/`.

Cost: ~$150–300/month minimum. Use when: real users beyond you, bank
conversations, or PDPL residency requirements.

## Connect the Lovable CRM to real data (after either path)

1. The API's CORS already allows `https://drip-saudi-abm.lovable.app`.
2. In Lovable (needs credits), tell the agent: "Set API_BASE_URL to
   `https://<your-public-url>` and add a login screen posting to /auth/login,
   storing the bearer token for all API calls." The typed client + demo
   fallback we built means this is a configuration change, not a rebuild.

## What deployment does NOT change

Send-safety (dry-run email), the audit trail, RLS tenancy, and the guarded
test suites all behave identically in the cloud. SSO/MFA, SOC2/PDPL
certification, and the 100k-contact load proof remain external-input items
tracked in the capability registry.
