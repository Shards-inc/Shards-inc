#!/usr/bin/env python3
"""Shards-inc NVIDIA fork synchroniser. Python standard library + authenticated gh.

Read-only by default. Use --execute to create genuine GitHub forks.
Licence classification is a conservative filter, NOT a full licence audit.
"""
import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

TARGET = "Shards-inc"
ORGS = (
    "NVIDIA", "NVIDIA-NeMo", "NVIDIA-AI-IOT", "triton-inference-server",
    "rapidsai", "NVIDIA-Omniverse", "isaac-sim", "ai-dynamo", "NVlabs",
)
# Prioritise useful missing projects before the long tail. No download or clone.
PRIORITY = (
    "isaac-sim/IsaacLab", "ai-dynamo/dynamo", "ai-dynamo/nixl",
    "NVlabs/instant-ngp", "NVlabs/tiny-cuda-nn", "NVlabs/FoundationPose",
    "NVlabs/Sana", "NVIDIA-AI-IOT/jetson-ai-lab",
    "NVIDIA-AI-IOT/torch2trt", "NVIDIA-AI-IOT/deepstream_python_apps",
    "NVIDIA-NeMo/DataDesigner", "NVIDIA-NeMo/Gym",
    "NVIDIA-NeMo/Megatron-Bridge", "NVIDIA-NeMo/Switchyard",
    "NVIDIA-NeMo/agent-hardener", "NVIDIA-NeMo/UserSim",
    "triton-inference-server/tutorials", "triton-inference-server/core",
    "triton-inference-server/pytorch_backend",
    "rapidsai/cugraph-gnn", "rapidsai/ucxx",
)
# Conservatively recognise common OSI-approved SPDX IDs.
OSI = {
    "0BSD", "AFL-3.0", "Apache-2.0", "Artistic-2.0", "BSD-2-Clause",
    "BSD-3-Clause", "BSL-1.0", "CDDL-1.0", "EPL-1.0", "EPL-2.0",
    "EUPL-1.2", "GPL-2.0", "GPL-3.0", "ISC", "LGPL-2.1", "LGPL-3.0",
    "MIT", "MIT-0", "MPL-2.0", "OFL-1.1", "OSL-3.0",
    "PostgreSQL", "Python-2.0", "Unlicense", "Zlib",
}

class GHError(RuntimeError):
    pass

def gh(args, payload=None):
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"] + args
    try:
        r = subprocess.run(
            cmd, input=json.dumps(payload) if payload is not None else None,
            text=True, capture_output=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GHError(str(exc)) from exc
    if r.returncode:
        raise GHError((r.stderr or r.stdout).strip()[:800])
    try:
        return json.loads(r.stdout)
    except ValueError as exc:
        raise GHError("Unexpected non-JSON response from GitHub CLI") from exc

def listing(path):
    pages = gh(["--paginate", "--slurp", path])
    if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
        raise GHError("Unexpected GitHub pagination response: " + path)
    return [item for page in pages for item in page]

def get_repo(full_name):
    try:
        return gh(["repos/" + full_name])
    except GHError as exc:
        msg = str(exc).lower()
        if "http 404" in msg or "(404)" in msg:
            return None
        raise

def parent_name(repo):
    return ((repo or {}).get("parent") or {}).get("full_name", "").lower()

def is_rate_limited(message):
    m = str(message).lower()
    return ("http 403" in m or "http 429" in m or "rate limit" in m
            or "secondary rate" in m or "abuse detection" in m)

def matching_existing(destination, upstream):
    candidate = get_repo(destination)
    return bool(candidate and candidate.get("fork") and
                parent_name(candidate) == upstream.lower())

def verify(destination, upstream):
    for seconds in (0, 2, 3, 5, 8):
        if seconds:
            time.sleep(seconds)
        if matching_existing(destination, upstream):
            return True
    return False

def fork(source, destination_name):
    body = {"name": destination_name, "default_branch_only": False}
    return gh(["-X", "POST", "--input", "-", "repos/" + source + "/forks"], body)

def destination_for(repo, taken):
    source = repo["full_name"]
    owner, name = source.split("/", 1)
    for proposed in (name, f"{owner}-{name}", f"nvidia-{owner}-{name}"):
        if proposed.lower() not in taken:
            return proposed
    return None

def main():
    parser = argparse.ArgumentParser(
        description="Discover NVIDIA-related public repositories and create real GitHub forks."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Create forks. By default only generate a dry-run report.")
    parser.add_argument("--limit", type=int, default=25,
                        help="Maximum NEW fork attempts per run (default 25, 0 = no cap).")
    parser.add_argument("--delay", type=float, default=6.0,
                        help="Minimum seconds between fork POST requests (default 6).")
    parser.add_argument("--org", action="append", choices=ORGS,
                        help="Restrict to one or more NVIDIA-related organisations.")
    parser.add_argument("--report", default=str(Path.home() / "nvidia-fork-audit.json"))
    args = parser.parse_args()

    if args.limit < 0 or args.delay < 2:
        parser.error("--limit must be nonnegative and --delay at least 2 seconds")
    if shutil.which("gh") is None:
        raise SystemExit("BLOCKED: install GitHub CLI (pkg install gh).")
    try:
        actor_data = gh(["user"])
        actor = actor_data["login"]
    except (GHError, KeyError, TypeError):
        raise SystemExit("BLOCKED: GitHub CLI authentication failed (gh auth login).")
    if actor.lower() != TARGET.lower():
        raise SystemExit(f"BLOCKED: authenticated as {actor}; required {TARGET}.")
    print(f"Account: {actor} | Mode: {'EXECUTE' if args.execute else 'DRY RUN'}")
    print("GitHub source inventory: " + ", ".join(args.org or ORGS))

    # Discover entire organisations through paginated GitHub REST lists.
    source_map = {}
    for org in (args.org or ORGS):
        try:
            repos = listing(f"orgs/{org}/repos?type=public&per_page=100")
        except GHError as exc:
            raise SystemExit(f"BLOCKED: Cannot inventory {org}: {exc}") from exc
        source_repos = [
            r for r in repos if not (r.get("fork") or r.get("archived")
                                   or r.get("disabled") or r.get("private"))
        ]
        for r in source_repos:
            source_map[r["full_name"].lower()] = r
        print(f"  {org}: {len(source_repos)} eligible nonarchived source repositories found")

    # Existing fork relationships must be established by GitHub metadata,
    # not guessed from identical names or old report files.
    try:
        own_repos = listing("user/repos?affiliation=owner&per_page=100")
        own_repos = [r for r in own_repos
                     if r.get("owner", {}).get("login", "").lower() == TARGET.lower()]
        taken = {r["name"].lower(): r for r in own_repos}
        upstreams = set()
        for r in own_repos:
            if r.get("fork"):
                detail = r if r.get("parent") else get_repo(r["full_name"])
                if detail is None:
                    raise GHError("Missing owned fork: " + r["full_name"])
                parent = parent_name(detail)
                if not parent:
                    raise GHError("Cannot verify existing fork parent: " + r["full_name"])
                upstreams.add(parent)
    except GHError as exc:
        raise SystemExit(f"BLOCKED: Cannot inspect existing Shards-inc forks: {exc}") from exc

    rank = {name.lower(): n for n, name in enumerate(PRIORITY)}
    candidates = sorted(
        source_map.values(),
        key=lambda r: (
            rank.get(r["full_name"].lower(), 100000),
            -(r.get("stargazers_count") or 0),
            r["full_name"].lower(),
        ),
    )
    report = {"account": TARGET, "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "mode": "execute" if args.execute else "dry-run",
              "organisations": args.org or list(ORGS),
              "sources_discovered": len(candidates), "results": []}
    rows = report["results"]
    attempted = 0
    verified = 0
    skipped_existing = 0
    skipped_license = 0
    problems = 0
    stop_reason = None

    def record(source, status, destination=None, reason=None):
        rows.append(dict(source=source, status=status, destination=destination,
                         reason=reason))
        if status not in ("already-forked", "licence-review", "batch-limit"):
            print(f"  {status}: {source}" +
                  (f" -> {destination}" if destination else "") +
                  (f" ({reason})" if reason else ""), flush=True)

    for repo in candidates:
        source = repo["full_name"]
        if source.lower() in upstreams:
            skipped_existing += 1
            record(source, "already-forked")
            continue
        spdx = ((repo.get("license") or {}).get("spdx_id") or "unknown")
        if spdx not in OSI:
            skipped_license += 1
            record(source, "licence-review", reason=spdx)
            continue
        name = destination_for(repo, taken)
        if not name:
            problems += 1
            record(source, "name-conflict", reason="all destination names taken")
            continue
        destination = TARGET + "/" + name
        if args.limit and attempted >= args.limit:
            record(source, "batch-limit", destination)
            continue
        if not args.execute:
            attempted += 1
            record(source, "ready", destination, "SPDX " + spdx)
            continue
        attempted += 1
        print(f"Fork request [{attempted}]: {source} -> {destination}", flush=True)
        try:
            fork(source, name)
        except GHError as exc:
            # A connection timeout can occur AFTER GitHub accepted the POST.
            try:
                if verify(destination, source):
                    verified += 1
                    upstreams.add(source.lower())
                    taken[name.lower()] = {"name": name}
                    record(source, "fork-verified", destination,
                           "accepted despite POST error")
                    time.sleep(args.delay)
                    continue
            except GHError as check_exc:
                stop_reason = "Cannot reconcile POST failure: " + str(check_exc)
                record(source, "unverified", destination, stop_reason)
                problems += 1
                break
            msg = str(exc)
            problems += 1
            record(source, "failed", destination, msg)
            if is_rate_limited(msg):
                stop_reason = "GitHub rate-limited this session; stopped safely"
            else:
                stop_reason = "Fork creation failed; stopped for inspection"
            break
        try:
            if not verify(destination, source):
                problems += 1
                stop_reason = "Fork accepted but upstream relationship not verified"
                record(source, "pending-verification", destination, stop_reason)
                break
        except GHError as exc:
            problems += 1
            stop_reason = "Could not verify upstream parent: " + str(exc)
            record(source, "pending-verification", destination, stop_reason)
            break
        verified += 1
        upstreams.add(source.lower())
        taken[name.lower()] = {"name": name}
        record(source, "fork-verified", destination, "SPDX " + spdx)
        time.sleep(args.delay)

    report["summary"] = {
        "new_verified_forks": verified, "new_attempts": attempted,
        "already_forked": skipped_existing, "licence_review": skipped_license,
        "problems": problems, "stop_reason": stop_reason,
    }
    report_path = Path(args.report).expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("\nSUMMARY: " + json.dumps(report["summary"]))
    print("Audit report: " + str(report_path))
    if not args.execute:
        print("DRY RUN ONLY: add --execute to create forks.")
    else:
        print("Run the same command again to continue the next batch (idempotent).")
    if stop_reason:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
