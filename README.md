# Mappings from ICTV to NCBITaxon

This repository generates and maintains mappings between ICTV (International Committee on Taxonomy of Viruses) and NCBITaxon ontologies using lexical matching.

## Automated Updates

The mappings are automatically updated weekly on Mondays at 00:00 UTC via a GitHub Actions workflow. The workflow:

1. Fetches all terms from the ICTV ontology via the OLS API
2. Splits matching work across parallel shards
3. Reuses the existing SSSOM file to skip ICTV subjects that are already mapped
4. Performs exact lexical matching against NCBITaxon with retries, backoff, and request timeouts
5. Uploads new shard mappings as workflow artifacts
6. Merges the existing file plus shard outputs into a final SSSOM TSV file
7. Commits and pushes changes if the mappings have been updated

The workflow can also be triggered manually from the Actions tab in GitHub.

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

To reproduce the sharded workflow locally:

```bash
uv sync
mkdir -p mappings/shards

for shard in 0 1 2 3 4 5 6 7; do
  uv run python src/map.py \
    --output mappings/shards/ictv_ncbitaxon_exact.shard-${shard}.sssom.tsv \
    --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
    --new-only \
    --shard-index ${shard} \
    --shard-count 8
done

uv run python src/merge_mappings.py \
  --input-glob 'mappings/shards/*.sssom.tsv' \
  --existing mappings/ictv_ncbitaxon_exact.sssom.tsv \
  --output mappings/ictv_ncbitaxon_exact.sssom.tsv
```

## License

CC0 - See [LICENSE](LICENSE) for details.
