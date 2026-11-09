import argparse

import requests

from map import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PAGE_ATTEMPTS,
    DEFAULT_PAGE_RETRY_DELAY,
    DEFAULT_TIMEOUT_SECONDS,
    build_session,
    get_all_terms,
    write_terms_file,
)


def main():
    parser = argparse.ArgumentParser(description="Download one complete ICTV snapshot for all mapping shards.")
    parser.add_argument("--output", "-o", required=True, help="Output JSON snapshot path")
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--backoff-factor", type=float, default=DEFAULT_BACKOFF_FACTOR)
    parser.add_argument("--page-attempts", type=int, default=DEFAULT_PAGE_ATTEMPTS)
    parser.add_argument("--page-retry-delay", type=float, default=DEFAULT_PAGE_RETRY_DELAY)
    args = parser.parse_args()
    if args.request_timeout <= 0 or args.max_retries < 0 or args.backoff_factor < 0:
        parser.error("Timeout must be positive; retries and backoff must be nonnegative")
    if args.page_attempts < 1 or args.page_retry_delay < 0:
        parser.error("Page attempts must be positive and page retry delay nonnegative")

    try:
        with build_session(args.max_retries, args.backoff_factor) as session:
            terms = get_all_terms(
                session,
                "ictv",
                args.request_timeout,
                page_attempts=args.page_attempts,
                page_retry_delay=args.page_retry_delay,
            )
        write_terms_file(args.output, "ictv", terms)
    except (requests.RequestException, ValueError, RuntimeError) as error:
        parser.exit(1, f"ICTV download failed: {error}\n")
    print(f"Saved {len(terms)} ICTV terms to {args.output}", flush=True)


if __name__ == "__main__":
    main()
