import argparse
from pathlib import Path

from map import mapping_key, write_mappings
from sssom.parsers import parse_sssom_table


def has_data_rows(path: Path) -> bool:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#") or line.startswith("subject_id\t"):
                continue
            return True
    return False


def load_mappings(path: Path):
    print(f"Loading mappings from {path}...")
    if not has_data_rows(path):
        print("  Loaded 0 mappings")
        return []
    msdf = parse_sssom_table(str(path))
    mappings = msdf.to_mappings()
    print(f"  Loaded {len(mappings)} mappings")
    return mappings


def main():
    parser = argparse.ArgumentParser(description="Merge sharded SSSOM mapping files.")
    parser.add_argument(
        "--input-glob",
        required=True,
        help="Glob for shard SSSOM TSV files, for example 'mappings/shards/*.tsv'",
    )
    parser.add_argument(
        "--existing",
        help="Optional existing SSSOM TSV file to include before shard outputs",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to the merged output SSSOM TSV file",
    )
    args = parser.parse_args()

    paths = sorted(Path().glob(args.input_glob))
    if not paths:
        raise FileNotFoundError(f"No shard files matched {args.input_glob}")

    deduped = {}
    if args.existing:
        existing_path = Path(args.existing)
        if existing_path.exists():
            for mapping in load_mappings(existing_path):
                deduped.setdefault(mapping_key(mapping), mapping)
        else:
            print(f"No existing mappings file found at {existing_path}")

    for path in paths:
        for mapping in load_mappings(path):
            deduped.setdefault(mapping_key(mapping), mapping)

    mappings = sorted(deduped.values(), key=mapping_key)
    print(f"Writing {len(mappings)} merged mappings from {len(paths)} shards to {args.output}")
    write_mappings(args.output, mappings)


if __name__ == "__main__":
    main()
