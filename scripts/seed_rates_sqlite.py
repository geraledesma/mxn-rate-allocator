"""Thin wrapper — use `rate-seed` CLI instead (rate_allocator.cli.seed)."""
from rate_allocator.cli.seed import main
if __name__ == "__main__":
    raise SystemExit(main())
