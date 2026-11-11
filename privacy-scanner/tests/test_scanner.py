import asyncio
import importlib
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

appmod = importlib.import_module('app')
client = TestClient(appmod.app)


def test_health():
    r=client.get('/health')
    assert r.status_code==200 and r.json()['authenticated'] is True


def test_permit_rejected():
    r=client.post('/v1/scans', json={'username':'octocat','consent':True,'sites':25}, headers={'x-scan-permit':'bad'})
    assert r.status_code==401


def test_validation():
    cases=[{'username':'not/a/url','consent':True,'sites':25},
           {'username':'octocat','consent':False,'sites':25},
           {'username':'octocat','consent':True,'sites':151}]
    for case in cases:
        assert client.post('/v1/scans',json=case).status_code in (400,422)


def test_status_mapping():
    class Code: value='Claimed'
    class Status: status=Code(); context=None
    value={'status':Status(),'url_user':'https://example.com/u/octocat'}
    assert appmod.map_maigret_result('Site',value,'octocat')['status']=='found'
    value['url_user']='javascript:alert(1)'
    assert appmod.map_maigret_result('Site',value,'octocat')['status']=='unknown'


def test_unknown_scan():
    r=client.get('/v1/scans/00000000-0000-0000-0000-000000000000')
    assert r.status_code==410


def test_authentication_is_per_scan(monkeypatch):
    async def verify(token, username):
        return token=='a'*64 and username=='octocat'
    async def stub_scanner(username, sites):
        return [{'source':'Known','status':'found','profile_url':'https://example.com/known','reason':None}]
    monkeypatch.setattr(appmod,'validate_permit',verify)
    monkeypatch.setattr(appmod,'execute_maigret',stub_scanner)
    with TestClient(appmod.app) as test:
        resp=test.post('/v1/scans',json={'username':'octocat','consent':True,'sites':25},headers={'x-scan-permit':'a'*64})
        assert resp.status_code==202
        body=resp.json()
        secret=body['status_token']
        url='/v1/scans/'+body['id']
        assert test.get(url).status_code==403
        assert test.get(url,headers={'x-scan-status-token':'wrong'}).status_code==403
        authorized=test.get(url,headers={'x-scan-status-token':secret})
        assert authorized.status_code==200
        assert 'status_token' not in authorized.json()


def test_claimed_homepage_is_not_a_profile():
    class Code: value='Claimed'
    class Status: status=Code(); context=None
    generic={'status': Status(), 'url_user': 'https://discord.com'}
    r=appmod.map_maigret_result('Discord',generic,'octocat')
    assert r['status']=='unknown'
    assert r['profile_url'] is None
    assert 'exact username' in r['reason']

def test_claimed_different_identity_is_not_a_match():
    class Code: value='Claimed'
    class Status: status=Code(); context=None
    for url in ('https://example.com/u/octocatters', 'https://example.com/u/other',
                'https://example.com/u/octocat_extra', 'http://example.com/u/octocat'):
        result=appmod.map_maigret_result('Site',{'status':Status(),'url_user':url},'octocat')
        assert result['status']=='unknown',url

def test_candidate_is_labeled_heuristic_not_verified():
    class Code: value='Claimed'
    class Status: status=Code(); context=None
    r=appmod.map_maigret_result('TikTok',{'status':Status(),'url_user':'https://www.tiktok.com/@octocat'},'octocat')
    assert r['status']=='found'
    assert r['verification']=='heuristic_candidate'


def test_terminal_snapshot_callback_uses_job_secret_and_excludes_runtime_state(monkeypatch):
    import json
    import httpx
    jid = 'f' * 8 + '-1234-1234-1234-' + 'a' * 12
    token = 'only-the-private-backend-knows-this'
    appmod.jobs[jid] = {
        'id': jid,
        'state': 'complete',
        'engine': 'maigret',
        'created_monotonic': 123.0,
        'status_token_digest': appmod.hash_token(token),
        'results': [{'source': 'Public', 'profile_url': 'https://example.com/u/octocat', 'status': 'found'}],
        'summary': {'attempted': 1, 'found': 1},
    }
    requests = []
    original = httpx.AsyncClient

    def intercept(req):
        payload = json.loads(req.content)
        assert req.url == appmod.RESULT_CALLBACK_URL
        assert req.headers['x-scan-status-token'] == token
        assert payload['id'] == jid
        assert 'created_monotonic' not in payload
        assert 'status_token_digest' not in payload
        assert 'username' not in payload
        requests.append(payload)
        return httpx.Response(201, json={'stored': True})

    def mock_client(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(intercept), **kwargs)

    monkeypatch.setattr(httpx, 'AsyncClient', mock_client)
    try:
        assert asyncio.run(appmod.publish_terminal_result(jid, token)) is True
        assert len(requests) == 1
    finally:
        appmod.jobs.pop(jid, None)


def test_finished_scan_publishes_results_without_exposing_status_token(monkeypatch):
    from uuid import uuid4
    jid = str(uuid4())
    token = 'secret-token'
    calls = []

    async def fake_search(username, sites):
        assert username == 'octocat' and sites == 25
        return [{'source': 'Example', 'status': 'found', 'profile_url': 'https://example.com/u/octocat'}]

    async def fake_publish(job, credential):
        calls.append((job, credential))
        return True

    monkeypatch.setattr(appmod, 'execute_maigret', fake_search)
    monkeypatch.setattr(appmod, 'publish_terminal_result', fake_publish)
    appmod.jobs[jid] = {
        'id': jid,
        'created_monotonic': __import__('time').monotonic(),
        'state': 'queued',
        'status_token_digest': appmod.hash_token(token),
        'summary': {},
        'results': [],
    }
    original_q = appmod.queued
    original_a = appmod.active
    appmod.queued = 1
    appmod.active = 0
    try:
        asyncio.run(appmod.run_one(jid, 'octocat', 25, token))
        assert appmod.jobs[jid]['state'] == 'complete'
        assert appmod.jobs[jid]['summary']['found'] == 1
        assert calls == [(jid, token)]
        assert 'status_token_digest' not in appmod.snapshot(appmod.jobs[jid])
    finally:
        appmod.jobs.pop(jid, None)
        appmod.queued = original_q
        appmod.active = original_a