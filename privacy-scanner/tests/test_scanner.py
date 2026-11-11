from fastapi.testclient import TestClient
import asyncio
import importlib
from pathlib import Path
import os
import pytest

os.environ['SCANNER_API_TOKEN'] = 'a' * 48
appmod = importlib.import_module('app')
client = TestClient(appmod.app)
HEADERS={'authorization': 'Bearer ' + 'a' * 48}


def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['authenticated'] is True


def test_auth():
    for headers in ({}, {'authorization':'Bearer not-valid'}):
        assert client.post('/v1/scans', headers=headers, json={'username':'octocat','consent':True,'sites':25}).status_code == 401


def test_validation():
    cases=[{'username':'not/a/url','consent':True,'sites':25},
           {'username':'octocat','consent':False,'sites':25},
           {'username':'octocat','consent':True,'sites':151}]
    for case in cases:
        assert client.post('/v1/scans', headers=HEADERS,json=case).status_code in (400,422)


def test_status_mapping():
    class Code:
        value='Claimed'
    class Status:
        status=Code()
        context=None
    result=appmod.map_maigret_result('MySite',{'status':Status(),'url_user':'https://example.com/foo'})
    assert result['status']=='found'
    assert result['profile_url']=='https://example.com/foo'
    result=appmod.map_maigret_result('MySite',{'status':Status(),'url_user':'javascript:alert(1)'})
    assert result['status']=='unknown'


def test_unknown_scan():
    r=client.get('/v1/scans/00000000-0000-0000-0000-000000000000',headers=HEADERS)
    assert r.status_code==410