# NVIDIA source fork synchroniser (Termux)

This tool inventories public, nonarchived, nonfork repositories from nine NVIDIA-related GitHub organisations and proposes **real GitHub forks** in the **Shards-inc** personal account. It does not clone or download source repositories, copy model weights, or use paid infrastructure.

## Prerequisites

- Python 3.9+
- GitHub CLI (`gh`) signed in as `Shards-inc`.
- GitHub account permission to create public forks.

## Mobile installation and use

```sh
curl -fsSL https://raw.githubusercontent.com/Shards-inc/Shards-inc/main/scripts/nvidia_fork_sync.py -o ~/nvidia_fork_sync.py
python ~/nvidia_fork_sync.py --limit 25
python ~/nvidia_fork_sync.py --execute --limit 25
```

Re-run the final command for subsequent batches. The script skips forks whose `parent.full_name` already matches an upstream source. The execution gate fails closed for any authenticated username other than `Shards-inc`.

## Safeguards

- Uses GitHub's official fork endpoint; preserves GitHub-recognised upstream parent.
- Filters out archived, disabled, private, and already-forked source repositories.
- Only attempts repositories with a recognised OSI SPDX identifier; reports missing, unknown and nonrecognised licences for manual review. **This metadata check is not a complete licence or asset audit.**
- Handles identical repository names from different upstream organisations by generating a destination name containing the upstream organisation.
- Serial requests with a delay (default 6 seconds); stops on failures or rate limits rather than flooding GitHub.
- Verifies newly created forks by checking their `parent.full_name`.
- Writes an audit report to `~/nvidia-fork-audit.json`; reports accepted-but-unverified forks separately.

## Configuration

```sh
python ~/nvidia_fork_sync.py                 # Dry run
python ~/nvidia_fork_sync.py --execute --limit 25
python ~/nvidia_fork_sync.py --execute --org NVlabs --limit 15
python ~/nvidia_fork_sync.py --execute --limit 0    # No batch cap: use cautiously
```

### Coverage

The inventory covers `NVIDIA`, `NVIDIA-NeMo`, `NVIDIA-AI-IOT`, `triton-inference-server`, `rapidsai`, `NVIDIA-Omniverse`, `isaac-sim`, `ai-dynamo`, and `NVlabs`. These are curated accounts, not a guarantee of *every* NVIDIA software project or separately hosted asset.

### Limits and restrictions

GitHub can return rate limits, permission errors, temporary networking failures, or accepted-but-not-yet-visible forks. Treat those results as **not verified** until GitHub's upstream relationship confirms them. Do not retry unrestrictedly on errors. Forking code does not grant licences to non-open-source model weights, datasets, proprietary assets, or NVIDIA trademarks. Forks do not automatically track future upstream updates.