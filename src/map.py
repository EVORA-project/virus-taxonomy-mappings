import argparse
import datetime
import os
import time
from functools import lru_cache
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from sssom import Mapping
from sssom.parsers import parse_sssom_table
from sssom.util import MappingSetDataFrame
from sssom.writers import write_table
from urllib3.util.retry import Retry

API_BASE = "https://www.ebi.ac.uk/ols4/api"
PAGE_SIZE = 1000
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.0


class TransientOlsError(RuntimeError):
    """Raised when OLS fails after retries, so we do not write partial results."""


def build_session(max_retries: int, backoff_factor: float) -> requests.Session:
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def iri_to_curie(iri: str) -> str:
    return iri.replace("http://purl.obolibrary.org/obo/NCBITaxon_", "ncbitaxon:").replace("http://ictv.global/id/", "ictv:")


def load_existing_mappings(filepath):
    """Load existing mappings from SSSOM file if it exists."""
    if not filepath or not os.path.exists(filepath):
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


def request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
):
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_all_terms(session: requests.Session, ontology: str, timeout: float):
    terms = []
    page = 0
    print(f"Fetching terms for ontology '{ontology}'...")
    while True:
        url = f"{API_BASE}/ontologies/{ontology}/terms"
        params = {"size": PAGE_SIZE, "page": page}
        data = request_json(session, url, params=params, timeout=timeout)
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


@lru_cache(maxsize=50000)
def quote_iri_for_ols(iri: str) -> str:
    return requests.utils.quote(requests.utils.quote(iri, safe=""), safe="")


def find_exact_ncbitaxon(
    session: requests.Session,
    label: str,
    *,
    timeout: float,
    pause_after_failure: float,
):
    url = f"{API_BASE}/search"
    params = {
        "q": label,
        "ontology": "ncbitaxon",
        "exact": True,
        "rows": 1,
    }
    try:
        data = request_json(session, url, params=params, timeout=timeout)
    except requests.RequestException as e:
        time.sleep(pause_after_failure)
        raise TransientOlsError(f"OLS search failed for '{label}' after retries: {e}") from e

    docs = data.get("response", {}).get("docs", [])
    if len(docs) > 0:
        doc = docs[0]
        term_iri = doc.get("iri")
        if not term_iri:
            return None
        term_iri_enc = quote_iri_for_ols(term_iri)
        term_url = f"{API_BASE}/ontologies/ncbitaxon/terms/{term_iri_enc}"
        try:
            return request_json(session, term_url, timeout=timeout)
        except requests.RequestException as e:
            time.sleep(pause_after_failure)
            raise TransientOlsError(f"OLS term lookup failed for '{term_iri}' after retries: {e}") from e
    return None


def ensure_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def labels_for_term(term: dict) -> list[str]:
    seen = set()
    labels = []
    for label in ensure_list(term.get("label", [])) + ensure_list(term.get("synonyms", [])):
        if not label:
            continue
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            labels.append(label)
    return labels


def shard_terms(terms: list[dict], shard_index: int, shard_count: int) -> Iterable[tuple[int, dict]]:
    for idx, term in enumerate(terms, start=1):
        if (idx - 1) % shard_count == shard_index:
            yield idx, term


def mapping_key(mapping: Mapping) -> tuple[str, str, str]:
    return (str(mapping.subject_id), str(mapping.predicate_id), str(mapping.object_id))


def write_mappings(filepath: str, mappings: list[Mapping]):
    prefix_map = {
        "ictv": "http://ictv.global/id/",
        "ncbitaxon": "http://purl.obolibrary.org/obo/NCBITaxon_",
        "skos": "http://www.w3.org/2004/02/skos/core#",
    }
    metadata = {
        "mapping_set_id": "ictv_to_ncbitaxon",
        "mapping_provider": "https://github.com/EVORA-project/virus-taxonomy-mappings",
        "license": "CC0",
        "mapping_set_title": "ICTV to NCBITaxon exact lexical mappings",
    }

    with open(filepath, "w", encoding="utf-8") as f:
        if not mappings:
            write_empty_table(f)
            return

        mappings = sorted(mappings, key=mapping_key)
        msdf = MappingSetDataFrame.from_mappings(mappings, converter=prefix_map, metadata=metadata)
        write_table(msdf, f)


def write_empty_table(file):
    file.write("# curie_map:\n")
    file.write("#   ictv: http://ictv.global/id/\n")
    file.write("#   ncbitaxon: http://purl.obolibrary.org/obo/NCBITaxon_\n")
    file.write("#   semapv: https://w3id.org/semapv/vocab/\n")
    file.write("#   skos: http://www.w3.org/2004/02/skos/core#\n")
    file.write("# license: CC0\n")
    file.write("# mapping_provider: https://github.com/EVORA-project/virus-taxonomy-mappings\n")
    file.write("# mapping_set_id: ictv_to_ncbitaxon\n")
    file.write("# mapping_set_title: ICTV to NCBITaxon exact lexical mappings\n")
    file.write(
        "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
        "mapping_justification\tmapping_tool\tmapping_date\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Generate ICTV to NCBITaxon mappings.")
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to the output SSSOM TSV file",
    )
    parser.add_argument(
        "--existing",
        help="Optional existing SSSOM TSV file used to skip already mapped subjects",
    )
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Only write mappings discovered during this run, while still using --existing to skip subjects",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Zero-based shard index to process",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Total number of shards",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="OLS request timeout in seconds",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Maximum retries for transient OLS failures",
    )
    parser.add_argument(
        "--backoff-factor",
        type=float,
        default=DEFAULT_BACKOFF_FACTOR,
        help="Exponential backoff factor between retries",
    )
    parser.add_argument(
        "--pause-after-failure",
        type=float,
        default=1.0,
        help="Small pause after an exhausted label lookup before continuing",
    )
    args = parser.parse_args()

    if args.shard_count < 1:
        raise ValueError("--shard-count must be at least 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise ValueError("--shard-index must be between 0 and shard-count - 1")

    session = build_session(args.max_retries, args.backoff_factor)
    existing_mappings = load_existing_mappings(args.existing) if args.existing else []
    existing_subjects = {str(mapping.subject_id) for mapping in existing_mappings}

    print(f"Found {len(existing_subjects)} ICTV terms already mapped")

    ictv_terms = get_all_terms(session, "ictv", args.request_timeout)
    total = len(ictv_terms)
    mappings = [] if args.new_only else list(existing_mappings)
    today = datetime.date.today().isoformat()

    new_mappings_count = 0
    skipped_count = 0
    lookup_cache = {}

    assigned_terms = list(shard_terms(ictv_terms, args.shard_index, args.shard_count))
    print(
        f"Shard {args.shard_index + 1}/{args.shard_count} will process "
        f"{len(assigned_terms)} of {total} ICTV terms"
    )

    for idx, term in assigned_terms:
        ictv_iri = term.get("iri")
        if not ictv_iri:
            print(f"  [{idx}/{total}] Skipping term without IRI")
            continue

        subject_id = iri_to_curie(ictv_iri)

        if subject_id in existing_subjects:
            skipped_count += 1
            if skipped_count % 100 == 0:
                print(f"  [{idx}/{total}] Skipped {skipped_count} already-mapped terms...")
            continue

        for label in labels_for_term(term):
            print(f"  [{idx}/{total}] Processing: '{label}'")
            if label in lookup_cache:
                match = lookup_cache[label]
            else:
                match = find_exact_ncbitaxon(
                    session,
                    label,
                    timeout=args.request_timeout,
                    pause_after_failure=args.pause_after_failure,
                )
                lookup_cache[label] = match
            if match:
                ncbi_iri = match.get("iri")
                if not ncbi_iri:
                    print(f"    Warning: OLS returned a match without an IRI for '{label}'")
                    continue
                object_id = iri_to_curie(ncbi_iri)
                object_labels = ensure_list(match.get("label", [])) + ensure_list(match.get("synonyms", []))
                if label.casefold() not in [l.casefold() for l in object_labels]:
                    print(f"    No accepted match: OLS returned {ncbi_iri} {object_labels} for '{label}'")
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
                        mapping_date=today,
                    )
                )
                new_mappings_count += 1
                existing_subjects.add(subject_id)
                print(f"    Match found: {subject_id} -> {object_id}")
                break
            else:
                print(f"    No match for '{label}'")

    output_description = "new mappings" if args.new_only else "total mappings"
    print(
        f"Mapping complete: {len(mappings)} {output_description} "
        f"({new_mappings_count} new, {skipped_count} skipped)"
    )
    write_mappings(args.output, mappings)


if __name__ == "__main__":
    main()
