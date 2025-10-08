import requests
import datetime
import argparse
import os
from sssom import Mapping
from sssom.writers import write_table
from sssom.util import MappingSetDataFrame
from sssom.parsers import parse_sssom_table

API_BASE = "https://www.ebi.ac.uk/ols4/api"
PAGE_SIZE = 1000

def iri_to_curie(iri: str) -> str:
    return iri.replace("http://purl.obolibrary.org/obo/NCBITaxon_", "ncbitaxon:").replace("http://ictv.global/id/", "ictv:")

def load_existing_mappings(filepath):
    """Load existing mappings from SSSOM file if it exists."""
    if not os.path.exists(filepath):
        print(f"No existing mappings file found at {filepath}")
        return []
    
    try:
        print(f"Loading existing mappings from {filepath}...")
        msdf = parse_sssom_table(filepath)
        existing = msdf.to_mappings()
        print(f"Loaded {len(existing)} existing mappings")
        return existing
    except Exception as e:
        print(f"Warning: Could not load existing mappings: {e}")
        return []

def get_all_terms(ontology: str):
    terms = []
    page = 0
    print(f"Fetching terms for ontology '{ontology}'...")
    while True:
        url = f"{API_BASE}/ontologies/{ontology}/terms"
        params = {"size": PAGE_SIZE, "page": page}
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("_embedded", {}).get("terms", [])
        if not batch:
            break
        terms.extend(batch)
        print(f"  Retrieved batch {page + 1}, total so far: {len(terms)}")
        links = data.get("_links", {})
        if "next" in links:
            page += 1
        else:
            break
    print(f"Completed fetching {len(terms)} terms for '{ontology}'.")
    return terms

def find_exact_ncbitaxon(label: str):
    url = f"{API_BASE}/search"
    params = {
        "q": label,
        "ontology": "ncbitaxon",
        "exact": True,
        "rows": 1
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    docs = data.get("response", {}).get("docs", [])
    if len(docs) > 0:
        doc = docs[0]
        term_iri = doc.get("iri")
        term_iri_enc = requests.utils.quote(requests.utils.quote(term_iri, safe=''), safe='')
        term_url = f"{API_BASE}/ontologies/ncbitaxon/terms/{term_iri_enc}"
        print(term_url)
        term_resp = requests.get(term_url)
        term_resp.raise_for_status()
        return term_resp.json()
    return None

def ensure_list(x):
    return x if isinstance(x, list) else [x]

def main():
    parser = argparse.ArgumentParser(description="Generate ICTV to NCBITaxon mappings.")
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to the output SSSOM TSV file"
    )
    args = parser.parse_args()

    # Load existing mappings to avoid re-querying
    existing_mappings = load_existing_mappings(args.output)
    
    # Build a set of subject_ids that already have mappings
    existing_subjects = set()
    for mapping in existing_mappings:
        existing_subjects.add(mapping.subject_id)
    
    print(f"Found {len(existing_subjects)} ICTV terms already mapped")

    ictv_terms = get_all_terms("ictv")
    total = len(ictv_terms)
    mappings = list(existing_mappings)  # Start with existing mappings
    today = datetime.date.today().isoformat()
    
    new_mappings_count = 0
    skipped_count = 0

    for idx, term in enumerate(ictv_terms, start=1):
        ictv_iri = term.get("iri")
        subject_id = iri_to_curie(ictv_iri)
        
        # Skip if we already have a mapping for this subject
        if subject_id in existing_subjects:
            skipped_count += 1
            if skipped_count % 100 == 0:
                print(f"  [{idx}/{total}] Skipped {skipped_count} already-mapped terms...")
            continue
        
        labels = ensure_list(term.get("label", [])) + ensure_list(term.get("synonyms", []))

        for label in labels:
            print(f"  [{idx}/{total}] Processing: '{label}'")
            match = find_exact_ncbitaxon(label)
            if match:
                ncbi_iri = match.get("iri")
                object_id = iri_to_curie(ncbi_iri)
                object_labels = ensure_list(match.get("label", [])) + ensure_list(match.get("synonyms", []))
                if not label.lower() in [l.lower() for l in object_labels]:
                    print(f"    ✗ OLS returned {ncbi_iri} {object_labels} as a match for '{label}' but it does not actually have that label")
                    continue
                mappings.append(
                    Mapping(
                        subject_id=subject_id,
                        subject_label=label,
                        predicate_id="skos:exactMatch",
                        object_id=object_id,
                        object_label=label,
                        mapping_justification="semapv:LexicalMatching",
                        mapping_tool="https://github.com/EVORA-project/virus-taxonomy-mappings",
                        mapping_date=today
                    )
                )
                new_mappings_count += 1
                existing_subjects.add(subject_id)  # Mark as mapped
                print(f"    ▶ Match found: {subject_id} -> {object_id}")
                break  # Found a mapping for this subject, no need to check other labels
            else:
                print(f"    ✗ No match for '{label}'")

    print(f"Mapping complete: {len(mappings)} total mappings ({new_mappings_count} new, {skipped_count} skipped)")

    prefix_map = {
        "ictv": "http://ictv.global/id/",
        "ncbitaxon": "http://purl.obolibrary.org/obo/NCBITaxon_",
        "skos": "http://www.w3.org/2004/02/skos/core#"
    }
    metadata = {
        "mapping_set_id": "ictv_to_ncbitaxon",
        "mapping_provider": "https://github.com/EVORA-project/virus-taxonomy-mappings",
        "license": "CC0",
        "mapping_set_title": "ICTV to NCBITaxon exact lexical mappings"
    }

    msdf = MappingSetDataFrame.from_mappings(mappings, converter=prefix_map, metadata=metadata)

    with open(args.output, "w", encoding="utf-8") as f:
        write_table(msdf, f)

if __name__ == "__main__":
    main()
