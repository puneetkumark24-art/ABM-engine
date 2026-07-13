# Drop your bank contact list(s) here

Accepted formats: `.xlsx` or `.csv`. One row per person. Drop as many files
as you want — every file in this folder gets imported.

Column headers (case-insensitive, order doesn't matter). Only **full_name**
and **institution** are required — everything else is optional:

| Column | Required | Notes |
|---|---|---|
| full_name | yes | |
| institution | yes | Bank/org name. Matched case-insensitively against existing organizations; created if new. |
| title / role | | job title |
| email | | |
| phone | | |
| whatsapp | | |
| linkedin_url | | |
| seniority | | e.g. c_suite, svp_evp, director, manager |
| persona | | Decision Maker / Influencer / Champion / Blocker / Connector |
| country | | |
| notes / background_notes | | |

Re-running the import is safe — a person already loaded (same full_name +
institution) gets updated, not duplicated.
