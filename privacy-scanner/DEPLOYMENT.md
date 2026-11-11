# Shards Privacy Hub — release evidence / 11 November 2026

## Service entrypoints

- Public privacy lab: https://privacy.shardsinc.co.uk/lab
- Quick username intelligence (21 fixed adapters): https://privacy.shardsinc.co.uk/lab/identity
- Deep discovery (ranked Maigret site selection): https://privacy.shardsinc.co.uk/lab/deep
- Render scanner health: https://shards-privacy-scanner.onrender.com/health
- Source PR: https://github.com/Shards-inc/Shards-inc/pull/1 (draft; review before merging)

## Deployment components

- Cloudflare script: `shards-privacy-portal`
- D1 binding: `EMAIL_DB`
- Rate-budget salt secret binding: `IDENTITY_RATE_SALT`
- Render service: `shards-privacy-scanner` in Frankfurt, Python/FastAPI, free tier
- Public worker routing: browser sends same-origin POST `/api/identity/deep/start`, GET `/api/identity/deep/status?id=...` to Cloudflare, Cloudflare sends authorisation-bearing requests to Render. Render redeems a single-use permit with Cloudflare D1.

## Acceptance checklist

| Gate | Status | Basis |
|---|---|---|
| Scanner local unit tests | PASS | 9 pytest tests in backend |
| Browser scripts parse | PASS | `node --check deep-ui.js` |
| Deep page has referenced controls | PASS | HTML element inspection |
| Cloudflare service health bridge | PASS | `GET /api/identity/deep/health` returned Maigret catalogue details when host warm |
| Controlled real job submitted | PASS | 202 accepted; job ID returned; permit redeemed |
| Authenticated job status | PASS | Cloudflare fetched Render job using its per-job token |
| Real site-result classification | PASS | 118 site-result records in controlled test |
| False-positive homepage filter | PASS | 10 raw candidate findings reduced to 9, Discord homepage rejected |
| Staging browser full workflow | PASS | 118 site results, 9 candidates, 23 unknown; cards rendered; JSON export control present |
| Production deployment | SEE LIVE SITE | Confirm exact current deployed Worker version in Cloudflare and repeat UI acceptance after release |
| Durable job queue/restart recovery | BLOCKED | Free Render memory is ephemeral |
| Paid customer readiness | BLOCKED | Auth, billing, processor/legal review and provider reliability outstanding |

## Rollback

Use Cloudflare Workers version deployments to restore the previous known-working release (21-source quick search remained available before deep UI). Do not roll back the D1 schema as this may invalidate concurrent jobs. Always check current deployed version and active scan state before changing traffic.

## Privacy obligations

- Keep raw usernames out of application logs and durable scan history.
- Treat 'claimed' site records as heuristic leads until corroborated.
- Never misrepresent upstream 403/429/CAPTCHA as proof of an absent account.
- Explain to users that public sites receive their username during the search.
- Delete expired temporary job and permit records and revise use of deterministic username hashes before a paid launch.