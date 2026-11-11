# Shards Privacy — Maigret deep-scan service

Dedicated public-username discovery worker for the Shards Privacy Hub. Current deployment: Render (Frankfurt), Cloudflare Worker front door at `https://privacy.shardsinc.co.uk/lab/deep`.

**Release status: public experimental preview, not commercial production-ready.** The API successfully completed a live end-to-end browser acceptance scan on 11 November 2026. A top-100 ranked-site selection yielded 118 site-result records in the tested Maigret version; this is not a guarantee that every site works.

## Trust boundaries

Browser → Cloudflare Worker → Render FastAPI service → approved Maigret site definitions.

- Browser only calls same-origin Cloudflare endpoints; Render does not expose an unauthenticated scanning operation.
- Cloudflare checks input, explicit consent and origin, then enforces per-network and global D1 budgets before issuing a **256-bit single-use permit**.
- Cloudflare stores a permit digest and a matching username digest. Render sends the permit and requested username back to the Cloudflare `/api/identity/deep/consume` verifier. D1 atomically consumes a matching, unexpired permit.
- Render replies with an opaque UUID job ID and a cryptographically random, per-job status token.
- Cloudflare stores a hash of a secure browser session cookie plus the Render status token. Subsequent status requests must present the original cookie; the browser never receives the Render token.
- Jobs and usernames exist in Render process memory only and expire after approximately 30 minutes from creation, or earlier after a service restart.
- An identical handle on multiple sites **does not prove common real-world ownership**. A Maigret `Claimed` status is only a **heuristic candidate**. Candidates require an HTTPS URL containing the exact submitted username in the URL path or query. Generic homepages and ambiguous ID-only URLs are downgraded to `unknown`.
- `unknown` includes site blocks, bot challenges, 403/429, malformed responses, generic links or timeouts. A negative result is not proof that a user has no account.

## Endpoints

| Endpoint | Caller | Behaviour |
|---|---|---|
| `GET /health` | Anyone | Liveness metadata; never starts a scan |
| `GET /health/catalogue` | Anyone | Site catalogue health; does not verify providers |
| `POST /v1/scans` | Cloudflare with `x-scan-permit` | JSON `{ "username":"octocat", "sites":100, "consent":true }`; returns HTTP 202 and one per-job token |
| `GET /v1/scans/{job_id}` | Cloudflare with `x-scan-status-token` | Returns `queued`, `running`, `complete`, or `failed` and evidence |

No email account enumeration, phone discovery, login automation, access-control bypass or third-party profile attribution is implemented.

## Live limits

- 100 ranked sites requested by frontend (150 maximum allowed per request). The actual site-result count may differ because the Maigret database expands or excludes specific checks.
- At most one active scan, two queued scans, 12 simultaneous outbound connections, 9-second per-source timeout and 105-second overall execution limit.
- Two starts per Cloudflare-observed network per UTC day; global preview budget is 20 per UTC day.
- Result expiry approximately 30 minutes; the Render Free service sleeps after idle and loses in-memory jobs across restarts.
- No authenticated account history, persistent result storage or SLA guarantees. This tier is **not suitable for paid customers**.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q tests/test_scanner.py
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

A local HTTP scan will not work unless a valid permit is issued and consumed by the configured Cloudflare gate (`ATTEST_URL` is currently the Shards Privacy endpoint). The test suite stubs the permit verifier and upstream sites; it must not be interpreted as a remote site acceptance test.

## Verification record

- 11 November 2026: nine local tests pass, including rejection of generic profile homepages and identity-mismatch URLs.
- 11 November 2026: Render deployed and its `/health` and `/health/catalogue` endpoints returned HTTP 200.
- 11 November 2026: real controlled backend scan of `cryptosingh1111` completed: 118 site results; original mapping produced 10 `claimed` results, including an invalid Discord homepage.
- 11 November 2026: revised validator downgraded the generic Discord result; staging browser ran and rendered 9 candidate matches from 118 site results, 23 unknown, with JSON export control available.
- Keep a record of the live production UI test separately. Provider-candidate matches have **not been independently verified as the same person**.

## Outstanding commercial readiness gates

1. Replace in-memory jobs with a durable, encrypted, tenant-isolated queue and controlled expiry/deletion, including post-crash reconciliation.
2. Upgrade to a host without free-tier sleep or missed scans, or design a reliable wake-and-retry queue.
3. Hardening: provider-specific source validation, false-positive calibration, request audit controls, and source terms-of-use compliance.
4. Replace shared-network quotas with authenticated user quotas and billing that fails closed.
5. Review and publish UK GDPR privacy notice, processor/subprocessor disclosures, DPIA where appropriate, retention/deletion and subject access request procedures, and an abuse response policy.
6. Add CI tests, independent security review and telemetry without logging raw queried identifiers.

The service and frontend are experimental; do not advertise 700+ verified sources, email-to-account attribution, or guaranteed anonymity checks.