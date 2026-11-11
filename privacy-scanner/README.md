# Shards Privacy — Private Maigret Scanner

A private HTTP service called only by `privacy.shardsinc.co.uk` via a bearer token. 
The public Cloudflare Worker performs request-budget, origin and consent validation.

## Security contract

- `GET /health` — no secret; reports `not_configured` if missing scanner token.
- `POST /v1/scans` — bearer token; JSON `{ "username": "octocat", "consent": true, "sites": 100 }`.
- `GET /v1/scans/{id}` — bearer token; returns `queued/running/complete/failed`.
- No public unauthenticated scan endpoints, no discovery emails or phone numbers, no identity linkage claims.
- Results are ephemeral; in-memory jobs are deleted after approximately 30 minutes, **not durable**.
- Scan max 150 sites; one active scan, two queued; 12 concurrent outbound requests, per-provider timeout 9 seconds, whole-job deadline 105 seconds.
- Unknown/captcha/timeout are not converted to `no_public_match`. Only confirmed `claimed` Maigret status becomes `found`.
- Web endpoints do not log the submitted username; check vendor logs and enable a stricter retention policy before collecting customer data.

## Running locally

```
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SCANNER_API_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" uvicorn app:app --port 8000
```

Render free service settings: `Root Directory: backend`, `Build: pip install -r requirements.txt`, `Start: uvicorn app:app --host 0.0.0.0 --port $PORT`, `Region: Frankfurt`. Supply `SCANNER_API_TOKEN` via a secret environment variable. Free Render instances sleep and lose active jobs; **not suitable for SLA-backed paid customers**. The production architecture requires a durable queue, persisted encrypted job state, an operator console, and an autoscaled worker.

## Next gates

1. Reproduce a real Maigret scan on deployed host and compare known controls for false positives.
2. Wire private Cloudflare Worker routes to backend via bearer binding, never embed tokens in frontend JavaScript.
3. Add durable D1/Queues/Redis job scheduling for restart recovery, budgets, cancellation, and per-user data deletion.
4. Restrict scanning to authorised personal exposure and permitted sources; publish UK privacy policy, retention and opt-out controls.
5. Monitor failures and site-definition health. A site in Maigret's database is not necessarily reliably queryable.