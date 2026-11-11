'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const form = $('scanForm'), start = $('start'), state = $('status');
  const led = $('led'), output = $('output'), stats = $('stats');
  const results = $('results'), filter = $('filter');
  let active = false, lastResult = null, startedAt = 0;
  const statuses = {found: 'CANDIDATE', unknown: 'UNCONFIRMED', no_public_match: 'NO PUBLIC MATCH', not_applicable: 'NOT APPLICABLE'};
  function text(parent, tag, value, cls='') {
    const el = document.createElement(tag); el.textContent = String(value ?? '');
    if (cls) el.className = cls; parent.appendChild(el); return el;
  }
  function setStatus(message, condition='') {
    state.textContent = message; led.className = 'led' + (condition ? ' ' + condition : '');
  }
  function render() {
    if (!lastResult) return;
    const data = lastResult.results || [];
    const chosen = filter.value;
    const order = {found:0, unknown:1, not_applicable:2, no_public_match:3};
    const items = data.filter(x => chosen === 'all' || x.status === chosen)
      .sort((a,b) => (order[a.status]??4)-(order[b.status]??4) || a.source.localeCompare(b.source));
    results.replaceChildren();
    if (items.length === 0) {
      text(results,'div','No sources in this category. This is not evidence of anonymity.','empty'); return;
    }
    for (const row of items) {
      const card = text(results,'article','', 'card');
      const top = text(card,'div','', 'cardtop');
      text(top,'h3',row.source);
      text(top,'span',statuses[row.status] || 'UNKNOWN', 'state ' + row.status);
      if (row.status === 'found' && row.profile_url) {
        const link = document.createElement('a');
        link.href = row.profile_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.className = 'profile'; link.textContent = 'OPEN PUBLIC PROFILE →'; card.appendChild(link);
        text(card,'p','Site heuristic indicated a profile. Verify this URL independently; matching handles are not proof of identity.');
      } else {
        text(card,'p',row.reason || 'No independently confirmed account from this provider.');
      }
    }
  }
  function summary(data) {
    stats.replaceChildren();
    for (const [label,value] of [['Site results',data.attempted],['Candidates',data.found],['No match',data.no_public_match],['Unknown',data.unknown],['Not applicable',data.not_applicable]]) {
      const item=text(stats,'div','', 'stat'); text(item,'small',label); text(item,'strong',value??'—');
    }
  }
  function sleep(ms) { return new Promise(resolve => setTimeout(resolve,ms)); }
  async function jsonFetch(url, options={}) {
    const res = await fetch(url, {credentials:'same-origin',cache:'no-store',...options});
    const value = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(value.error || ('HTTP '+res.status+' from scanner gateway'));
    return value;
  }
  async function prewarm() {
    // Render Free instances suspend after inactivity; the health path wakes the instance.
    // This does not submit a username or consume a deep-scan budget.
    for (let i=0;i<2;i++) {
      setStatus(i ? 'Scanner is starting; checking its readiness again…' : 'Checking scanner readiness…', 'running');
      try {
        const health=await jsonFetch('/api/identity/deep/health');
        if (health.status==='ok') return;
      } catch(e) {
        if (i===1) throw new Error('Scanner is unavailable. The host may be waking or restarting. No deep scan was started.');
      }
      await sleep(6500);
    }
    throw new Error('Scanner is not ready. No deep scan was started.');
  }
  async function poll(id) {
    // No fake progress percentages: backend reports queued/running/complete/failed.
    for(let i=0;i<48;i++) {
      await sleep(i===0?2000:3500);
      const data=await jsonFetch('/api/identity/deep/status?id='+encodeURIComponent(id));
      setStatus('Job '+data.state+' · elapsed '+Math.round((Date.now()-startedAt)/1000)+'s', 'running');
      if(data.state==='complete') return data;
      if(data.state==='failed') throw new Error(data.error || 'Scanner reported a failed job');
    }
    throw new Error('Scan exceeded the preview time limit. You can retry later.');
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if(active || !form.reportValidity()) return;
    const username=$('username').value.trim();
    if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,30}[A-Za-z0-9]$/.test(username) || !$('consent').checked) {
      setStatus('Valid username and explicit authorisation are required.', 'failed'); return;
    }
    active=true; start.disabled=true; start.textContent='SCANNING…';
    output.hidden=true; results.replaceChildren(); lastResult=null; startedAt=Date.now();
    try {
      await prewarm();
      setStatus('Requesting a one-use authorisation permit…','running');
      const queued=await jsonFetch('/api/identity/deep/start',{
        method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username,consent:true})
      });
      if(!queued.id) throw new Error('Scanner did not supply a job identifier');
      setStatus('Scan accepted. Inspecting ranked public sites…','running');
      const completed=await poll(queued.id);
      lastResult=completed; summary(completed.summary||{}); output.hidden=false;
      filter.value='found'; render();
      setStatus('Complete: '+(completed.summary?.found||0)+' candidates from '+(completed.summary?.attempted||0)+' site results.', 'complete');
    } catch(error) {
      setStatus(error.message || 'Scan unavailable; no result can be claimed.', 'failed');
    } finally {
      active=false; start.disabled=false; start.textContent='START DEEP SCAN ↗';
    }
  });
  filter.addEventListener('change',render);
  $('export').addEventListener('click',() => {
    if (!lastResult || lastResult.state !== 'complete') return;
    const payload={engine:'maigret',notice:'Candidate matches are heuristic, not identity proof',summary:lastResult.summary,results:lastResult.results,completed_at:lastResult.completed_at};
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='shards-public-footprint.json';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
})();