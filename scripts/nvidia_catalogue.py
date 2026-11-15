#!/usr/bin/env python3
"""Shards-inc NVIDIA fork catalogue and upstream change monitor (stdlib only).

Never merges/updates source forks. GitHub issue notifications are opt-in via
--notify-only and confined to Shards-inc/Shards-inc.
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ACCOUNT = "Shards-inc"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "nvidia-catalogue"
CONFIG = ROOT / "config" / "nvidia_catalogue_watch.json"
ISSUE_TITLE = "NVIDIA upstream watch - Shards integration candidates"

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def api(path="", query=None, variables=None, method="GET", body=None):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN or GITHUB_TOKEN required")
    url = "https://api.github.com/graphql" if query else "https://api.github.com" + path
    payload = {"query":query,"variables":variables or {}} if query else body
    raw = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization":"Bearer "+token,
               "Accept":"application/vnd.github+json",
               "X-GitHub-Api-Version":"2022-11-28",
               "User-Agent":"Shards-NVIDIA-Catalogue/1.0"}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    attempts = 3 if query or method == "GET" else 1
    for attempt in range(attempts):
        req = urllib.request.Request(url,data=raw,headers=headers,
                                     method="POST" if query else method)
        try:
            with urllib.request.urlopen(req,timeout=50) as response:
                value = json.loads(response.read().decode())
            if isinstance(value,dict) and value.get("errors"):
                raise RuntimeError("GraphQL error: "+str(value["errors"])[:600])
            return value
        except urllib.error.HTTPError as exc:
            detail = exc.read(450).decode(errors="replace")
            if exc.code in (403,429):
                raise RuntimeError("GitHub permission/rate limit HTTP "+str(exc.code)+": "+detail)
            if exc.code not in (502,503,504) or attempt == attempts-1:
                raise RuntimeError("GitHub HTTP "+str(exc.code)+": "+detail)
        except (urllib.error.URLError,TimeoutError) as exc:
            if attempt == attempts-1:
                raise RuntimeError("Network unavailable: "+str(exc))
        time.sleep((3,9)[attempt])
    raise RuntimeError("GitHub retry budget exceeded")

def load(path,default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=True,indent=2,sort_keys=True)+"\n",
                    encoding="utf-8")

def commit_oid(branch):
    return ((branch or {}).get("target") or {}).get("oid") or ""

GQL = """
query($login:String!,$after:String){
 user(login:$login){
  login
  repositories(first:100,after:$after,ownerAffiliations:OWNER,
     isFork:true,orderBy:{field:NAME,direction:ASC}){
    pageInfo{hasNextPage endCursor}
    nodes{
     nameWithOwner url description isFork isPrivate isArchived updatedAt pushedAt
     stargazerCount primaryLanguage{name} licenseInfo{spdxId}
     defaultBranchRef{name target{... on Commit{oid}}}
     parent{nameWithOwner url defaultBranchRef{name target{... on Commit{oid}}}}
    }
  }
 }
}
"""

def all_forks():
    cursor = None
    result = []
    seen = set()
    for _ in range(100):
        value = api(query=GQL,variables={"login":ACCOUNT,"after":cursor})
        user = (value.get("data") or {}).get("user")
        if not user or user.get("login","").lower()!=ACCOUNT.lower():
            raise RuntimeError("Unexpected user response")
        conn = user["repositories"]
        for repo in conn["nodes"]:
            if not repo or repo["nameWithOwner"].lower() in seen:
                raise RuntimeError("Missing/duplicate fork from GitHub GraphQL")
            seen.add(repo["nameWithOwner"].lower())
            result.append(repo)
        page = conn["pageInfo"]
        if not page["hasNextPage"]:
            return result
        next_cursor = page.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("Invalid GitHub pagination cursor")
        cursor = next_cursor
    raise RuntimeError("Pagination safety cap exceeded")

def heads_for_watch(watchlist):
    targets = list(dict.fromkeys(
        row["upstream"] for row in watchlist if row.get("watch")
    ))
    if len(targets)>80:
        raise RuntimeError("Watchlist too large")
    pieces=[]
    for i,full in enumerate(targets):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+",full):
            raise RuntimeError("Invalid watch source name: "+full)
        owner,name=full.split("/",1)
        pieces.append("r"+str(i)+":repository(owner:"+json.dumps(owner)+
                      ",name:"+json.dumps(name)+"){nameWithOwner pushedAt "
                      "defaultBranchRef{name target{... on Commit{oid}}}}")
    if not targets:
        return {}
    value=api(query="query { "+" ".join(pieces)+" }")
    data=value.get("data") or {}
    result={}
    for i,full in enumerate(targets):
        repo=data.get("r"+str(i))
        result[full.lower()]={"upstream":full,
                              "head":commit_oid(repo.get("defaultBranchRef")) if repo else "",
                              "pushed_at":repo.get("pushedAt") if repo else None}
    return result

def changes_since(watch,previous):
    latest=dict(previous.get("heads") or {})
    changes=[]
    seeded=[]
    unavailable=[]
    for upstream,row in sorted(watch.items()):
        new=row.get("head")
        if not new:
            unavailable.append(row["upstream"])
            continue
        old=latest.get(upstream)
        if old and old!=new:
            changes.append({"upstream":row["upstream"],
                            "old_head":old,"new_head":new,
                            "compare_url":"https://github.com/"+row["upstream"]+
                            "/compare/"+old+"..."+new})
        if not old:
            seeded.append(row["upstream"])
        latest[upstream]=new
    return ({"schema_version":1,"heads":latest},
            {"generated_at":now(),"changes":changes,"seeded":seeded,
             "unavailable_heads":unavailable})

def category(upstream,description,curated):
    if curated:
        return curated["category"]
    name=(upstream+" "+(description or "")).lower()
    patterns=[
        ("Kernel / Security",("security","guardrail","red-team","safety","garak")),
        ("MCP / Agent Hub",("agent","mcp","skill","workflow","orchestrat")),
        ("RAG / Data",("retriev","rag","dataset","cudf","cuml","rapids")),
        ("Inference",("triton","tensorrt","inference","vllm","llm")),
        ("Robotics / Simulation",("robot","isaac","cosmos","omniverse","physx","jetson")),
        ("Infrastructure",("container","kubernetes","operator","cuda","gpu","docker")),
        ("Models / Training",("model","train","transformer","nemotron","nemo"))
    ]
    for label,words in patterns:
        if any(x in name for x in words):
            return label
    return "Research / Other"

def catalogue(config, forks, watch):
    valid={x.lower() for x in config["nvidia_related_owners"]}
    priorities={x["upstream"].lower():x for x in config["watchlist"]}
    entries=[]
    for repo in forks:
        if not repo["isFork"] or repo["isPrivate"]:
            continue
        if repo["nameWithOwner"].split("/",1)[0].lower()!=ACCOUNT.lower():
            raise RuntimeError("Repository outside Shards-inc returned")
        parent=repo.get("parent")
        if not parent or not parent.get("nameWithOwner"):
            raise RuntimeError("Missing upstream lineage: "+repo["nameWithOwner"])
        upstream=parent["nameWithOwner"]
        if upstream.split("/",1)[0].lower() not in valid:
            continue
        important=priorities.get(upstream.lower())
        wh=watch.get(upstream.lower()) or {}
        upstream_sha=wh.get("head") or commit_oid(parent.get("defaultBranchRef"))
        fork_sha=commit_oid(repo.get("defaultBranchRef"))
        entries.append({
            "fork":repo["nameWithOwner"],"fork_url":repo["url"],
            "upstream":upstream,"upstream_url":parent["url"],
            "description":repo.get("description") or "",
            "licence":(repo.get("licenseInfo") or {}).get("spdxId") or "Unknown",
            "stars":repo.get("stargazerCount") or 0,
            "language":(repo.get("primaryLanguage") or {}).get("name") or "Unknown",
            "category":category(upstream,repo.get("description"),important),
            "priority":important["priority"] if important else "Archive",
            "shards_use":important["shards_use"] if important else "",
            "monitoring":bool(important and important.get("watch")),
            "fork_head":fork_sha,"upstream_head":upstream_sha,
            "same_head":bool(fork_sha and upstream_sha and fork_sha==upstream_sha),
            "pushed_at":repo.get("pushedAt"),"updated_at":repo.get("updatedAt"),
            "archived":repo.get("isArchived"),
        })
    rank={"P0":0,"P1":1,"P2":2,"Archive":3}
    entries.sort(key=lambda x:(rank.get(x["priority"],4),x["category"],x["fork"].lower()))
    cats=dict(sorted(collections.Counter(x["category"] for x in entries).items()))
    return {"schema_version":1,"generated_at":now(),"account":ACCOUNT,
            "total":len(entries),"categories":cats,"entries":entries,
            "priority_count":sum(x["priority"]!="Archive" for x in entries),
            "monitored_count":sum(x["monitoring"] for x in entries),
            "disclaimer":"A fork does not imply build readiness, licence coverage or upstream compatibility."}

def markdown_index(data,changes):
    lines=[
        "# NVIDIA fork catalogue - Shards-inc","",
        "Generated from verified GitHub fork-parent relationships.","",
        "Last scan: "+data["generated_at"]+"  ",
        "NVIDIA-related forks: "+str(data["total"])+"  ",
        "Curated integration candidates: "+str(data["priority_count"])+"  ",
        "Monitored forks: "+str(data["monitored_count"]),"",
        "## Browse","",
        "- [Mobile-searchable HTML](index.html) (GitHub Pages or local files)",
        "- [Full JSON index](catalogue.json)",
        "- [Latest watch report](changes.json)","",
        "## Strategic candidates","",
        "| Priority | Fork | Upstream | Domain | Shards use |",
        "| --- | --- | --- | --- | --- |",
    ]
    for x in data["entries"]:
        if x["priority"]=="Archive":
            continue
        use=x["shards_use"].replace("|","/").replace("\n"," ")
        lines.append("| "+x["priority"]+" | ["+x["fork"]+"]("+x["fork_url"]+
                     ") | ["+x["upstream"]+"]("+x["upstream_url"]+") | "+
                     x["category"]+" | "+use+" |")
    lines.extend(["","## Categories",""])
    for cat,count in data["categories"].items():
        lines.append("- "+cat+": "+str(count))
    lines.extend(["","## Monitoring","",
                 "New upstream SHA changes: "+str(len(changes["changes"]))+".",
                 "No source code is merged automatically. SHA changes are review signals, not merge instructions."])
    (OUTPUT/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

def scan():
    conf=load(CONFIG,{})
    if conf.get("target_account")!=ACCOUNT:
        raise RuntimeError("Account gate mismatch: must be Shards-inc")
    all_items=all_forks()
    observed=heads_for_watch(conf["watchlist"])
    state,changes=changes_since(observed,load(OUTPUT/"watch-state.json",{"heads":{}}))
    data=catalogue(conf,all_items,observed)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    write(OUTPUT/"catalogue.json",data)
    (OUTPUT/"catalogue-data.js").write_text(
        "window.SHARDS_NVIDIA_CATALOGUE = "+
        json.dumps(data,ensure_ascii=True,separators=(",",":"))+";\n",encoding="utf-8")
    write(OUTPUT/"watch-state.json",state)
    write(OUTPUT/"changes.json",changes)
    markdown_index(data,changes)
    summary=("Shards NVIDIA catalogue: "+str(data["total"])+" verified forks, "+
             str(data["priority_count"])+" curated, "+str(data["monitored_count"])+
             " monitored, "+str(len(changes["changes"]))+" new upstream SHA changes.")
    print(summary)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## NVIDIA catalogue scan\n\n"+summary+"\n\n")
    return 0

def notify():
    report=load(OUTPUT/"changes.json",{})
    if not isinstance(report.get("changes"),list):
        raise RuntimeError("Changes report missing or malformed")
    issues=api("/repos/Shards-inc/Shards-inc/issues?state=all&per_page=100")
    existing=next((x for x in issues if x.get("title")==ISSUE_TITLE and
                   "pull_request" not in x),None)
    if existing is None:
        body=("A durable watch for high-priority NVIDIA upstream repositories.\n\n"
              "Config: https://github.com/Shards-inc/Shards-inc/blob/main/"
              "config/nvidia_catalogue_watch.json\n\n"
              "Catalogue: https://github.com/Shards-inc/Shards-inc/tree/main/"
              "docs/nvidia-catalogue\n\n"
              "Initial run seeds upstream SHAs without claiming any change. "
              "Future upstream changes are posted as comments. No merges are automated.")
        existing=api("/repos/Shards-inc/Shards-inc/issues",method="POST",
                     body={"title":ISSUE_TITLE,"body":body})
        print("Watch issue created: "+str(existing["number"]))
    if existing.get("state")!="open":
        print("Watch issue closed by user; no notifications posted")
        return 0
    if not report["changes"]:
        print("No upstream changes since prior baseline")
        return 0
    lines=["## Upstream HEAD updates - "+report["generated_at"],"",
           "Review signals only; no automatic merges or production approvals.","",
           "| Upstream | Previous | New | Compare |",
           "|---|---|---|---|"]
    for x in report["changes"]:
        lines.append("| "+x["upstream"]+" | "+x["old_head"][:12]+" | "+
                     x["new_head"][:12]+" | [Compare]("+x["compare_url"]+") |")
    api("/repos/Shards-inc/Shards-inc/issues/"+str(existing["number"])+"/comments",
        method="POST",body={"body":"\n".join(lines)})
    print("Posted upstream changes to issue "+str(existing["number"]))
    return 0

def selftest():
    assert category("NVIDIA/garak","",None)=="Kernel / Security"
    assert category("NVIDIA/NemoClaw","",{"category":"Agent OS"})=="Agent OS"
    observed={"nvidia/test":{"upstream":"NVIDIA/test","head":"b"*40}}
    previous={"heads":{"nvidia/test":"a"*40}}
    state,report=changes_since(observed,previous)
    assert len(report["changes"])==1 and state["heads"]["nvidia/test"]=="b"*40
    _,report=changes_since(observed,state)
    assert not report["changes"]
    _,report=changes_since(observed,{"heads":{}})
    assert not report["changes"] and report["seeded"]==["NVIDIA/test"]
    print("Selftests passed")
    return 0

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify-only",action="store_true")
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.selftest:
        return selftest()
    if args.notify_only:
        return notify()
    return scan()

if __name__=="__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("BLOCKED: "+str(e),file=sys.stderr)
        sys.exit(2)
