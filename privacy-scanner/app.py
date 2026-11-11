"""Private, bounded Maigret scanner API for the Shards Privacy Hub.

The public Cloudflare Worker is the only intended caller. A scan is short-lived and
held in process memory; this free-host preview is not a durable job queue.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import hmac
import hashlib
import secrets
import httpx
import importlib.resources
import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse, unquote
from uuid import uuid4

from fastapi import FastAPI, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

APP_NAME = 'Shards Private Scan Engine'
USER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,30}[A-Za-z0-9]$')
ACTIVE_LIMIT = 1
QUEUE_LIMIT = 2
JOBS_LIMIT = 24
TTL_SECONDS = 1800
ATTEST_URL = 'https://privacy.shardsinc.co.uk/api/identity/deep/consume'
RESULT_CALLBACK_URL = 'https://privacy.shardsinc.co.uk/api/identity/deep/complete'
MAX_SITES = int(os.getenv('SCANNER_MAX_SITES', '150'))
LOGGER = logging.getLogger('shards_privacy_scanner')
# Third-party site errors sometimes embed the searched username, full profile URLs,
# response headers or anti-bot HTML in exception messages. These are personal data.
# Never route those diagnostics to the provider's persistent application logs.
SITE_LOGGER = logging.getLogger('shards_privacy_scanner.site_checks')
SITE_LOGGER.addHandler(logging.NullHandler())
SITE_LOGGER.propagate = False
SITE_LOGGER.disabled = True
for _namespace in ('maigret', 'maigret.checking', 'socid_extractor', 'aiohttp', 'curl_cffi'):
    _logger = logging.getLogger(_namespace)
    _logger.addHandler(logging.NullHandler())
    _logger.propagate = False
    _logger.disabled = True


app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
# Never persist username scans to disk or log the submitted username.
jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
queued = 0
active = 0
lock = asyncio.Lock()
scan_semaphore = asyncio.Semaphore(ACTIVE_LIMIT)


class ScanInput(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    sites: int = Field(default=100, ge=25, le=150)
    consent: bool


async def validate_permit(token: str, username: str) -> bool:
    """Single-use scan permit; no shared credentials across cloud accounts."""
    if not re.fullmatch(r'[0-9a-f]{64}', token):
        return False
    try:
        async with httpx.AsyncClient(timeout=13, follow_redirects=False) as client:
            r = await client.post(ATTEST_URL, json={'token': token, 'username': username})
        return r.status_code == 200 and r.json() == {'authorised': True}
    except Exception:
        LOGGER.warning('Scan permit attestation failed; request denied')
        return False


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k not in ('created_monotonic', 'status_token_digest')}


def evict_old() -> None:
    now = time.monotonic()
    for jid, item in list(jobs.items()):
        if item['state'] in ('complete', 'failed') and now - item['created_monotonic'] > TTL_SECONDS:
            jobs.pop(jid, None)
    while len(jobs) > JOBS_LIMIT:
        # Never evict an active job to make room.
        done = next((jid for jid, item in jobs.items() if item['state'] in ('complete', 'failed')), None)
        if done is None:
            break
        jobs.pop(done, None)


def map_maigret_result(name: str, value: dict[str, Any], searched_username: str) -> dict[str, Any]:
    result = value.get('status')
    enum = getattr(result, 'status', None)
    state = str(getattr(enum, 'value', 'Unknown')).lower()
    status = {'claimed': 'found', 'available': 'no_public_match', 'illegal': 'not_applicable'}.get(state, 'unknown')
    profile = str(value.get('url_user') or '')
    parsed = urlparse(profile)
    reason = str(getattr(result, 'context', '') or '')[:140] if status == 'unknown' else None
    if status == 'found':
        # Maigret's "Claimed" state is a detection heuristic, not proof of
        # common identity. Do not count homepages or ambiguous ID-only URLs.
        # A provider-specific authenticated adapter must corroborate ID-only
        # account links before they can be classified as a positive result.
        path_query = unquote(parsed.path + ('?' + parsed.query if parsed.query else ''))
        handle_pattern = r'(?<![A-Za-z0-9_.-])' + re.escape(searched_username) + r'(?![A-Za-z0-9_.-])'
        if (parsed.scheme != 'https' or not parsed.hostname or '.' not in parsed.hostname
                or parsed.username or parsed.password
                or not re.search(handle_pattern, path_query, re.IGNORECASE)):
            status = 'unknown'
            reason = 'Site heuristic did not return an exact username-bearing public profile URL'
    return {
        'source': str(name)[:90],
        'status': status,
        'profile_url': profile[:600] if status == 'found' else None,
        'verification': 'heuristic_candidate' if status == 'found' else None,
        'reason': reason,
    }


async def execute_maigret(username: str, sites: int) -> list[dict[str, Any]]:
    # Import on use to allow health checks even when package dependency is broken.
    from maigret import search as maigret_search
    from maigret.sites import MaigretDatabase

    path = importlib.resources.files('maigret').joinpath('resources/data.json')
    db = MaigretDatabase().load_from_path(str(path))
    selected = db.ranked_sites_dict(top=sites, excluded_tags=['nsfw', 'dating'])
    # 12 concurrent site connections avoids triggering large bursts and host bans.
    data = await maigret_search(
        username=username,
        site_dict=selected,
        logger=SITE_LOGGER,
        timeout=9,
        max_connections=12,
        retries=0,
        is_parsing_enabled=False,
        no_progressbar=True,
    )
    return [map_maigret_result(n, row, username) for n, row in data.items()]


async def publish_terminal_result(jid: str, status_secret: str) -> bool:
    """Write a short-lived result snapshot to Cloudflare D1 through an authenticated callback.

    Failure here must not fabricate success or make the underlying scan disappear;
    the browser can still poll the in-memory source. The callback is idempotent.
    """
    item = jobs.get(jid)
    if not item or item['state'] not in ('complete', 'failed'):
        return False
    payload = snapshot(item)
    # No username, IP, permit, or secret may be included in the persisted snapshot.
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for attempt in range(3):
            try:
                r = await client.post(
                    RESULT_CALLBACK_URL,
                    json=payload,
                    headers={'x-scan-status-token': status_secret, 'content-type': 'application/json'},
                )
                if r.status_code in (200, 201):
                    return True
            except (httpx.HTTPError, ValueError):
                pass
            if attempt < 2:
                await asyncio.sleep(0.75 * (attempt + 1))
    LOGGER.warning('Result preservation callback failed; ephemeral results remain available')
    return False


async def run_one(jid: str, username: str, sites: int, status_secret: str) -> None:
    global active, queued
    async with scan_semaphore:
        async with lock:
            queued -= 1
            active += 1
            jobs[jid]['state'] = 'running'
            jobs[jid]['started_at'] = datetime.now(timezone.utc).isoformat()
        try:
            # Hard overall deadline, independent of per-source timeouts.
            result = await asyncio.wait_for(execute_maigret(username, sites), timeout=105)
            summary = {
                'attempted': len(result),
                'found': sum(1 for x in result if x['status'] == 'found'),
                'no_public_match': sum(1 for x in result if x['status'] == 'no_public_match'),
                'unknown': sum(1 for x in result if x['status'] == 'unknown'),
                'not_applicable': sum(1 for x in result if x['status'] == 'not_applicable'),
            }
            jobs[jid].update(state='complete', summary=summary, results=result,
                             completed_at=datetime.now(timezone.utc).isoformat())
        except Exception:
            LOGGER.warning('Scanner job failed; external exception details withheld for privacy')
            jobs[jid].update(state='failed', error='Search engine unavailable or timed out',
                             completed_at=datetime.now(timezone.utc).isoformat())
        finally:
            try:
                await publish_terminal_result(jid, status_secret)
            except Exception:
                LOGGER.warning('Could not preserve terminal scan state; exception details withheld')
            async with lock:
                active -= 1
            evict_old()


@app.get('/health')
async def health() -> dict[str, Any]:
    return {'status': 'ok',
            'service': 'shards-privacy-maigret', 'mode': 'ephemeral_permit_bridge',
            'authenticated': True}


@app.get('/health/catalogue')
async def catalogue() -> dict[str, Any]:
    """Public, read-only discovery-engine readiness; does not scan usernames."""
    try:
        from maigret.sites import MaigretDatabase
        path = importlib.resources.files('maigret').joinpath('resources/data.json')
        db = MaigretDatabase().load_from_path(str(path))
        count = len(db.ranked_sites_dict(top=500, excluded_tags=['nsfw', 'dating']))
        if count < 50:
            raise ValueError('Site catalogue unexpectedly small')
        return {'status': 'ok', 'engine': 'maigret', 'configured_sites_sample': count,
                'default_site_limit': MAX_SITES, 'real_scan_tested': False,
                'note': 'Catalogue readiness is not proof that every remote site works'}
    except Exception:
        LOGGER.warning('Maigret catalogue readiness check failed; exception details withheld')
        raise HTTPException(503, 'Maigret catalogue unavailable')


@app.post('/v1/scans', status_code=202)
async def start_scan(payload: ScanInput, response: Response, x_scan_permit: str | None = Header(default=None)) -> dict[str, Any]:
    global queued
    username = payload.username.strip()
    if not USER_RE.fullmatch(username) or not payload.consent:
        raise HTTPException(400, 'Valid username and authorisation are required')
    if payload.sites > MAX_SITES:
        raise HTTPException(400, 'Requested scan exceeds configured site budget')
    if not x_scan_permit or not await validate_permit(x_scan_permit, username):
        raise HTTPException(401, 'Single-use scan permit required')
    async with lock:
        evict_old()
        if active + queued >= ACTIVE_LIMIT + QUEUE_LIMIT or len(jobs) >= JOBS_LIMIT:
            raise HTTPException(429, 'Scanner at capacity; retry later')
        jid = str(uuid4())
        status_secret = secrets.token_urlsafe(32)
        queued += 1
        jobs[jid] = {
            'status_token_digest': hash_token(status_secret),
            'id': jid,
            'state': 'queued',
            'requested_sites': payload.sites,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'created_monotonic': time.monotonic(),
            'engine': 'maigret',
            'results': [],
            'summary': {'attempted': 0, 'found': 0, 'no_public_match': 0, 'unknown': 0, 'not_applicable': 0},
        }
    asyncio.create_task(run_one(jid, username, payload.sites, status_secret))
    response.headers['Cache-Control'] = 'no-store'
    return {**snapshot(jobs[jid]), 'status_token': status_secret}


@app.get('/v1/scans/{jid}')
async def scan_result(jid: str, response: Response, x_scan_status_token: str | None = Header(default=None)) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    if not re.fullmatch(r'[0-9a-f-]{36}', jid):
        raise HTTPException(404, 'Unknown scan')
    evict_old()
    value = jobs.get(jid)
    if value is None:
        raise HTTPException(410, 'Scan is no longer available (expired or worker restarted)')
    if not x_scan_status_token or not hmac.compare_digest(hash_token(x_scan_status_token), value['status_token_digest']):
        raise HTTPException(403, 'Scan session token required')
    return snapshot(value)