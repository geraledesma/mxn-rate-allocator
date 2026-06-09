"""Thin wrapper — use `rate-scrape` CLI instead (rate_allocator.cli.scrape)."""
from rate_allocator.cli.scrape import main
if __name__ == "__main__":
    raise SystemExit(main())
