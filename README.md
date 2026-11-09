# Mappings from ICTV to NCBITaxon

This repository generates and maintains mappings between ICTV (International Committee on Taxonomy of Viruses) and NCBITaxon ontologies using lexical matching.

## Automated Updates

The mappings are automatically updated weekly on Mondays at 00:00 UTC via a GitHub Actions workflow. The workflow:

1. Fetches and validates a complete ICTV term snapshot once via the OLS API, then shares it as a workflow artifact.
2. Splits matching work across eight shards, running two in parallel against that same snapshot.
3. Reuses the existing SSSOM file as a cache of discovered mapping triples and already-checked label matches.
4. Performs exact lexical matching against NCBITaxon with retries, backoff, and request timeouts.
5. Allows a manual backfill mode that rechecks existing labels to discover additional valid exact matches for the same ICTV subject.
6. Refreshes stale NCBITaxon preferred labels when a cached mapping triple now points to a renamed current term.
7. Uploads new shard mappings as workflow artifacts.
8. Merges the existing file plus shard outputs into a final SSSOM TSV file.
9. Commits and pushes changes if the mappings have been updated.

The workflow can also be triggered manually from the Actions tab in GitHub.

### OLS Outage Recovery

ICTV page downloads get up to four rounds of the usual request retries per page, with 30, 60 and 120-second cooldowns between rounds. Previously downloaded pages are retained in memory instead of being fetched again. The preparation job is capped at 30 minutes. Logs are unbuffered and show the current page, recovery attempt and cooldown.

Only a complete, validated snapshot is uploaded. All eight mapping shards still run separately; they no longer each download the full ICTV ontology. A fresh snapshot is required for every workflow run so new MSL terms are not hidden by a stale ontology cache. The existing SSSOM mapping cache and the opt-in backfill behavior are unchanged.

If the ICTV download still fails, mapping and merge jobs do not start and the published SSSOM is left untouched. Rerun the failed preparation job once OLS recovers. NCBITaxon lookup failures during matching remain retryable on later runs, as before.

## Generated Mappings

The generated mappings are stored in:
- `mappings/ictv_ncbitaxon_exact.sssom.tsv` - SSSOM format mappings file

## Running Locally

To generate mappings locally as a single job:

```bash
# Install dependencies
uv sync

# Generate mappings
uv run python src/map.py --output mappings/ictv_ncbitaxon_exact.sssom.tsv
```

To reproduce the default sharded workflow locally:

```bash
uv sync
mkdir -p mappings/shards
uv run python src/fetch_terms.py --output mappings/shards/ictv-terms.json

for shard in 0 1 2 3 4 5 6 7; do
  uv run python src/map.py \
    --output mappings/shards/ictv_ncbitaxon_exact.shard-${shard}.sssom.tsv \
    --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
    --terms-file mappings/shards/ictv-terms.json \
    --new-only \
    --shard-index ${shard} \
    --shard-count 8
done

uv run python src/merge_mappings.py \
  --input-glob 'mappings/shards/*.sssom.tsv' \
  --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
  --output mappings/ictv_ncbitaxon_exact.sssom.tsv
```

To run a one-time backfill that rechecks labels already present in the cache and can discover additional exact matches for the same ICTV subject:

```bash
uv sync
mkdir -p mappings/shards
uv run python src/fetch_terms.py --output mappings/shards/ictv-terms.json

for shard in 0 1 2 3 4 5 6 7; do
  uv run python src/map.py \
    --output mappings/shards/ictv_ncbitaxon_exact.shard-${shard}.sssom.tsv \
    --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
    --terms-file mappings/shards/ictv-terms.json \
    --new-only \
    --recheck-existing-labels \
    --shard-index ${shard} \
    --shard-count 8
done

uv run python src/merge_mappings.py \
  --input-glob 'mappings/shards/*.sssom.tsv' \
  --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
  --output mappings/ictv_ncbitaxon_exact.sssom.tsv
```

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

Tests use a local HTTP server and mocked OLS responses, without calling the live OLS service.

## License

CC0 - See [LICENSE](LICENSE) for details.
