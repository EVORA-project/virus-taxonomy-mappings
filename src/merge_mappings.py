import argparse
from pathlib import Path

from map import mapping_key, write_mappings
from sssom.parsers import parse_sssom_table


def load_mappings(path: Path):
    print(f"Loading shard mappings from {path}...")
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
        "--output", "-o",
        required=True,
        help="Path to the merged output SSSOM TSV file",
    )
    args = parser.parse_args()

    paths = sorted(Path().glob(args.input_glob))
    if not paths:
        raise FileNotFoundError(f"No shard files matched {args.input_glob}")

    deduped = {}
    for path in paths:
        for mapping in load_mappings(path):
            deduped.setdefault(mapping_key(mapping), mapping)

    mappings = sorted(deduped.values(), key=mapping_key)
    print(f"Writing {len(mappings)} merged mappings from {len(paths)} shards to {args.output}")
    write_mappings(args.output, mappings)


if __name__ == "__main__":
    main()
