"""Thin wrapper — use `rate-ingest` CLI instead (rate_allocator.cli.ingest)."""
from rate_allocator.cli.ingest import main
if __name__ == "__main__":
    raise SystemExit(main())
