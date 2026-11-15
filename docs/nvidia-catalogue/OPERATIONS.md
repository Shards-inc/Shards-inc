# NVIDIA source intelligence — operations

## Production endpoints

- **Searchable catalogue:** https://catalogue.shardsinc.co.uk/
- **GitHub Actions workflow:** https://github.com/Shards-inc/Shards-inc/actions/workflows/nvidia-catalogue.yml
- **Monitored change log:** https://github.com/Shards-inc/Shards-inc/issues/2
- **Catalogue JSON:** https://github.com/Shards-inc/Shards-inc/blob/main/docs/nvidia-catalogue/catalogue.json
- **Watchlist config:** https://github.com/Shards-inc/Shards-inc/blob/main/config/nvidia_catalogue_watch.json
- **Worker source:** https://github.com/Shards-inc/Shards-inc/blob/main/workers/nvidia-catalogue-proxy.mjs

## Behaviour

A GitHub Actions job runs on the default branch at **06:17 UTC daily**, or via workflow_dispatch. It:

1. Queries Shards-inc-owned GitHub forks using GraphQL (100 per page).
2. Includes only actual GitHub forks with verifiable parent ownership in the configured nine NVIDIA-related organisations.
3. Generates `catalogue.json`, `catalogue-data.js` and the Markdown catalogue index.
4. Reads current default-branch commit SHAs for selected upstream projects.
5. Compares them against the previous committed baseline in `watch-state.json`.
6. Updates generated records in the Shards-inc profile repository without force-pushing.
7. Creates or reuses **one persistent GitHub issue** and comments only when upstream HEAD SHAs change.

The first observation seeds the baseline; it does not fabricate a change event. Changed upstream SHAs are **review signals only** and never cause source merging, PR creation or execution.

The domain is served by the Cloudflare Worker `shards-nvidia-catalogue` under the **Shards-inc Free Website zone**. The Worker is a read-only allowlisted static proxy to the committed GitHub documents, with 60–180-second response caching and no secrets, tracking, database, external paid service or execution of forked code.

## Controls and security

- Scope: **Shards-inc** only, never Shards-foundation.
- All imported fork metadata is rendered as text in the browser; search does not execute repository descriptions.
- Current categories use heuristics except for the explicitly curated watchlist. They are **not engineering certifications**.
- Repository SHA equality/difference alone does not establish Git history divergence or an upgrade requirement.
- Licence metadata in the catalogue is informational. The separate fork-acquisition tool retains its licence gate; unclassified projects must be reviewed separately.
- A closed watch issue stays closed. Reopening it requires an authorised user action.
- No repository code is automatically merged, installed or deployed.
- The Cloudflare Worker is separate from other Shards websites and does not modify existing Worker routes.

## Maintenance

Adjust the curated priorities, categories and watch setting in `config/nvidia_catalogue_watch.json`. Commit to main; the workflow updates the index and monitor baseline. Its daily run also refreshes new forks added via Termux.

For urgent refreshes, use **Actions → Shards NVIDIA catalogue and upstream watch → Run workflow** in GitHub. Confirm status and logs after execution.

If the catalogue becomes unavailable, inspect the workflow runs, committed `catalogue-data.js`, Cloudflare Worker `shards-nvidia-catalogue` and its custom-domain mapping. Cloudflare's domain provisioning can take time after initial attachment.

## Deferred enhancements

- Richer provenance: SPDX file parsing and manual review classification for the 663 nonrecognised/licence-review candidates.
- Ahead/behind comparisons using the GitHub compare API before recommending upstream synchronisation.
- Topic extraction and maintainer/activity scoring for integration prioritisation.
- A Shards Agent Hub endpoint linking catalogue entries to internal integration proposals and security reviews.
