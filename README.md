# Mappings from ICTV to NCBITaxon

This repository generates and maintains mappings between ICTV (International Committee on Taxonomy of Viruses) and NCBITaxon ontologies using lexical matching.

## Automated Updates

The mappings are automatically updated weekly on Mondays at 00:00 UTC via a GitHub Actions workflow. The workflow:

1. Fetches all terms from the ICTV ontology via the OLS API
2. Performs exact lexical matching against NCBITaxon
3. Generates updated mappings in SSSOM TSV format
4. Commits and pushes changes if the mappings have been updated

The workflow can also be triggered manually from the Actions tab in GitHub.

## Generated Mappings

The generated mappings are stored in:
- `mappings/ictv_ncbitaxon_exact.sssom.tsv` - SSSOM format mappings file

## Running Locally

To generate mappings locally:

```bash
# Install dependencies
uv sync

# Generate mappings
uv run python src/map.py --output mappings/ictv_ncbitaxon_exact.sssom.tsv
```

## License

CC0 - See [LICENSE](LICENSE) for details.
