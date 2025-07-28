import requests
import datetime
import argparse
from sssom import Mapping
from sssom.writers import write_table
from sssom.util import MappingSetDataFrame

API_BASE = "https://www.ebi.ac.uk/ols4/api"
PAGE_SIZE = 1000

def iri_to_curie(iri: str) -> str:
    prefix = "http://purl.obolibrary.org/obo/"
    if iri.startswith(prefix):
        curie_part = iri[len(prefix):]
        return curie_part.replace("_", ":")
    return iri

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

    ictv_terms = get_all_terms("ictv")
    total = len(ictv_terms)
    mappings = []
    today = datetime.date.today().isoformat()

    for idx, term in enumerate(ictv_terms, start=1):
        labels = ensure_list(term.get("label", [])) + ensure_list(term.get("synonyms", []))

        for label in labels:
            print(f"  [{idx}/{total}] Processing: '{label}'")
            ictv_iri = term.get("iri")
            subject_id = term.get("obo_id") or iri_to_curie(ictv_iri)
            match = find_exact_ncbitaxon(label)
            if match:
                ncbi_iri = match.get("iri")
                object_id = match.get("obo_id") or iri_to_curie(ncbi_iri)
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
                print(f"    ▶ Match found: {subject_id} -> {object_id}")
            else:
                print(f"    ✗ No match for '{label}'")

    print(f"Exact match search complete: {len(mappings)} mappings found.")

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
