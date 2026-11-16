#!/usr/bin/env python3
"""Read-only NVIDIA source-licence evidence inventory for Shards-inc.

This does NOT classify a project as safe to fork, redistribute or use.
It never forks, clones, patches, synchronises or executes upstream code.
Runs incremental standard GitHub /license endpoint checks, preserving source
provenance. Uses the acquisition script's *exact* scope and SPDX allowlist.
"""
import argparse
import collections
import datetime as dt
import json
import re
import shutil
import sys
import time
from pathlib import Path

from nvidia_fork_sync import GHError, ORGS, OSI, TARGET, gh, listing
from nvidia_catalogue import all_forks

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "nvidia_catalogue_watch.json"
REPORT = ROOT / "docs" / "nvidia-catalogue" / "licence-review.json"
README = ROOT / "docs" / "nvidia-catalogue" / "LICENCE_REVIEW.md"

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8")

def metadata_status(spdx):
    if spdx in OSI:
        return "recognised-in-acquisition-gate"
    if not spdx or spdx.lower() in ("unknown", "noassertion", "none"):
        return "no-recognised-spdx-in-repository-metadata"
    if spdx.upper() in ("OTHER", "NONE"):
        return "custom-or-unidentified-metadata"
    return "non-allowlisted-spdx-requires-review"

def current_sources():
    repos = {}
    for org in ORGS:
        page = listing("orgs/" + org + "/repos?type=public&per_page=100")
        for item in page:
            if item.get("fork") or item.get("archived") or item.get("disabled") or item.get("private"):
                continue
            name = item.get("full_name")
            if not name or name.split("/", 1)[0].lower() != org.lower():
                raise GHError("Unexpected source owner in GitHub listing: " + str(name))
            repos[name.lower()] = item
        print("Source organisation " + org + ": " + str(sum(
            1 for name in repos if name.startswith(org.lower()+"/"))))
    return repos

def source_exclusions(sources, verified_parents, priorities):
    eligible = []
    ready_missing = []
    for source in sources.values():
        name = source["full_name"]
        if name.lower() in verified_parents:
            continue
        lic = source.get("license") or {}
        spdx = lic.get("spdx_id") or "unknown"
        if spdx in OSI:
            ready_missing.append({"upstream": name, "spdx": spdx})
            continue
        watch = priorities.get(name.lower(), {})
        eligible.append({
            "upstream":name,
            "url":source.get("html_url") or "https://github.com/"+name,
            "description":source.get("description") or "",
            "metadata_spdx":spdx,
            "metadata_license_name":lic.get("name") or "",
            "metadata_status":metadata_status(spdx),
            "fork_exists":False,
            "stars":source.get("stargazers_count") or 0,
            "pushed_at":source.get("pushed_at"),
            "updated_at":source.get("updated_at"),
            "priority":watch.get("priority") or "Unranked",
            "shards_use":watch.get("shards_use") or "",
            "evidence":{"status":"not-yet-inspected"}
        })
    rank = {"P0":0, "P1":1, "P2":2, "Unranked":3}
    eligible.sort(key=lambda v:(rank.get(v["priority"],4), -v["stars"],v["upstream"].lower()))
    return eligible, ready_missing

def inspect_license(repo):
    """Inspect GitHub's standard licence endpoint. No file content persisted."""
    source = repo["upstream"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",source):
        raise GHError("Invalid upstream name: " + source)
    try:
        data = gh(["repos/"+source+"/license"])
    except GHError as exc:
        raw = str(exc)
        if "HTTP 404" in raw or "Not Found" in raw:
            return {
                "status":"standard-licence-endpoint-not-found",
                "checked_at":now(),
                "caution":"404 does not establish the absence of a licence in other files or subdirectories"
            }
        raise
    lic = data.get("license") or {}
    return {
        "status":"standard-licence-evidence-found",
        "checked_at":now(),
        "path":data.get("path"),
        "url":data.get("html_url"),
        "sha":data.get("sha"),
        "detected_spdx":lic.get("spdx_id") or "unknown",
        "detected_name":lic.get("name") or "unknown",
        "caution":"Metadata and a discovered licence file are evidence, not an independent legal approval"
    }

def audit(inspect_limit, delay):
    if shutil.which("gh") is None:
        raise RuntimeError("gh CLI is required")
    # GitHub Actions authenticates as github-actions[bot], whereas Termux must
    # authenticate directly as Shards-inc. In CI, check the exact repository.
    ci_repo = __import__("os").environ.get("GITHUB_REPOSITORY")
    if ci_repo:
        if ci_repo.lower() != "shards-inc/shards-inc":
            raise RuntimeError("BLOCKED: CI repository must be Shards-inc/Shards-inc")
    else:
        actor = gh(["user"]).get("login")
        if not actor or actor.lower() != TARGET.lower():
            raise RuntimeError("BLOCKED: GitHub actor must be Shards-inc")
    config = read_json(CONFIG,{})
    if config.get("target_account") != TARGET:
        raise RuntimeError("BLOCKED: licence audit must target Shards-inc")
    priorities = {i["upstream"].lower():i for i in config["watchlist"]}
    sources = current_sources()
    own = all_forks()
    if any(not r.get("parent") or not r["parent"].get("nameWithOwner") for r in own):
        raise RuntimeError("BLOCKED: a Shards-inc fork has an unknown upstream parent")
    parents = {r["parent"]["nameWithOwner"].lower() for r in own if r.get("isFork")}
    rows, ready_missing = source_exclusions(sources, parents, priorities)
    previous = read_json(REPORT,{})
    previous_by_name = {r.get("upstream", "").lower():r for r in previous.get("candidates",[])}
    inspected_this_run = 0
    # Reuse only when the same source push timestamp is unchanged.
    for row in rows:
        prior = previous_by_name.get(row["upstream"].lower())
        if prior and prior.get("pushed_at") == row["pushed_at"]:
            evidence=prior.get("evidence",{})
            if evidence.get("status") in (
                "standard-licence-evidence-found","standard-licence-endpoint-not-found"
            ):
                row["evidence"] = evidence
                continue
        if inspected_this_run >= inspect_limit:
            continue
        try:
            row["evidence"] = inspect_license(row)
            inspected_this_run += 1
            print("Inspected " + row["upstream"] + ": " + row["evidence"]["status"])
        except GHError as exc:
            # Do not silently misclassify an outage or a 403 as "no licence".
            row["evidence"] = {"status":"inspection-blocked",
                               "checked_at":now(),"reason":str(exc)[:250]}
            print("BLOCKED while inspecting " + row["upstream"], file=sys.stderr)
            break
        time.sleep(delay)
    counts=dict(sorted(collections.Counter(row["metadata_status"] for row in rows).items()))
    evidence_counts=dict(sorted(collections.Counter(row["evidence"]["status"] for row in rows).items()))
    output = {
        "schema_version":1,
        "generated_at":now(),
        "target":TARGET,
        "source_organisations":list(ORGS),
        "sources_discovered":len(sources),
        "verified_upstream_parents":len(parents),
        "candidates_count":len(rows),
        "new_file_inspections":inspected_this_run,
        "recognised_spdx_not_yet_forked":ready_missing,
        "metadata_statuses":counts,
        "evidence_statuses":evidence_counts,
        "disclaimer":"Read-only evidence inventory, NOT legal advice or permission to fork.",
        "candidates":rows
    }
    save_json(REPORT,output)
    build_markdown(output)
    print("SUMMARY: " + json.dumps({
        "sources_discovered":len(sources),
        "candidates_needing_review":len(rows),
        "inspected_now":inspected_this_run,
        "evidence":evidence_counts,
        "ready_missing":len(ready_missing)
    }))
    if len(ready_missing):
        print("NOTE: Unexpected recognised-SPDX unforked sources; do not assume why.")
    if output["evidence_statuses"].get("inspection-blocked"):
        return 2
    return 0

def build_markdown(report):
    lines = [
        "# NVIDIA licence evidence review — Shards-inc","",
        "**Read-only**: no project is automatically forked, cloned, executed, merged or re-licensed.",
        "",
        "Last scan: "+report["generated_at"]+"  ",
        "Source repositories discovered: "+str(report["sources_discovered"])+"  ",
        "Current candidates requiring review: "+str(report["candidates_count"])+"  ",
        "Verified distinct fork parents under Shards-inc: "+str(report["verified_upstream_parents"])+"",
        "",
        "## Classification policy","",
        "- This process reuses the existing acquisition tool's **exact SPDX allowlist**.",
        "- Missing/unknown SPDX metadata is **not evidence that a repository is unlicensed**.",
        "- A non-allowlisted identifier is **not a determination of proprietary licensing**.",
        "- A discovered LICENSE file is **evidence only**, not a licence-compliance clearance.",
        "- Code, model weights, datasets, trademarks and patents may have different terms.",
        "- No acquisition or integration occurs without additional project-specific checks.",
        "",
        "## Metadata classifications",""
    ]
    for name,count in report["metadata_statuses"].items():
        lines.append("- "+name+": "+str(count))
    lines.extend(["","## Standard GitHub licence-file endpoint evidence",""])
    for name,count in report["evidence_statuses"].items():
        lines.append("- "+name+": "+str(count))
    lines.extend(["","## Curated high-priority review candidates","",
                  "| Upstream | Priority | Metadata SPDX | File evidence | Potential use |",
                  "|---|---|---|---|---|"])
    for row in report["candidates"]:
        if row["priority"] not in ("P0","P1","P2"):
            continue
        name=row["upstream"]
        url=row["url"]
        use=row["shards_use"].replace("|","/").replace("\n"," ")
        lines.append("| ["+name+"]("+url+") | "+row["priority"]+" | "+
                     row["metadata_spdx"]+" | "+row["evidence"]["status"]+
                     " | "+use+" |")
    lines.extend(["","[Full JSON evidence inventory](licence-review.json)",
                  "",
                  "## Decisions requiring human review","",
                  "Before proposing a fork, check actual licence text, restrictions in the",
                  "repository, external assets, contributor rights and applicable redistribution",
                  "conditions. Preserve upstream attribution. Do not treat GitHub metadata",
                  "as authoritative legal clearance."])
    README.parent.mkdir(parents=True,exist_ok=True)
    README.write_text("\n".join(lines)+"\n",encoding="utf-8")

def selftest():
    assert metadata_status("MIT")=="recognised-in-acquisition-gate"
    assert metadata_status("NOASSERTION")=="no-recognised-spdx-in-repository-metadata"
    assert metadata_status("unknown")=="no-recognised-spdx-in-repository-metadata"
    assert metadata_status("Custom-1.0")=="non-allowlisted-spdx-requires-review"
    samples=[
        {"full_name":"NVIDIA/a","license":{"spdx_id":"MIT"},"stargazers_count":1},
        {"full_name":"NVIDIA/b","license":{"spdx_id":"NOASSERTION"},"stargazers_count":2}
    ]
    rows, missing=source_exclusions(
        {i["full_name"].lower():i for i in samples},
        {"nvidia/a"}, {})
    assert len(rows)==1 and rows[0]["upstream"]=="NVIDIA/b"
    assert not missing
    print("Licence-audit self-tests passed")
    return 0

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inspect-limit",type=int,default=40,
                   help="Max fresh GitHub licence endpoint GETs per run; default 40")
    p.add_argument("--delay",type=float,default=3,
                   help="Seconds between file inspections; default 3")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        return selftest()
    if args.inspect_limit < 0 or args.inspect_limit > 100 or args.delay < 2:
        p.error("Max 100 inspections; delay >= 2 seconds; limit >= 0")
    return audit(args.inspect_limit,args.delay)

if __name__=="__main__":
    try:
        sys.exit(main())
    except (GHError,RuntimeError,ValueError,KeyError,TypeError) as exc:
        print("BLOCKED: "+str(exc), file=sys.stderr)
        sys.exit(2)
