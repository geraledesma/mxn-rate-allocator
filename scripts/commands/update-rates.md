# update-rates

Scrape current rates from tasas.mx and ingest them into the SQLite SCD2 database.

## Steps

1. **Run the scraper** against tasas.mx and write `data/scraped_live.yaml`:
   ```bash
   rate-scrape --output data/scraped_live.yaml
   ```
   Report which institutions were scraped and their top rates. Flag any `[SKIP]` or `[WARN]` lines.

2. **Ingest into DB** — run SCD2 ingest with a timestamped note:
   ```bash
   RATE_ALLOCATOR_DB_URL="sqlite:///data/rates.db" \
     rate-ingest data/scraped_live.yaml \
     --note "scraped from tasas.mx $(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```

3. **Re-ingest manual additions** — PlataCard and Mifel are not on tasas.mx; always re-apply them after a scrape:
   ```bash
   RATE_ALLOCATOR_DB_URL="sqlite:///data/rates.db" \
     rate-ingest data/manual_additions.yaml \
     --note "manual additions re-applied after scrape $(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```

4. **Verify changes** — query the DB and report what changed:
   ```python
   from rate_allocator.persistence import create_db_engine, session_scope
   from rate_allocator.persistence.history import load_recent_tier_rate_changes
   engine = create_db_engine('sqlite:///data/rates.db')
   with session_scope(engine) as s:
       events = load_recent_tier_rate_changes(s, limit=50)
   for e in events:
       print(f"{e.institution_name} tramo {e.tier_index+1}: {e.old_rate*100:.2f}% → {e.new_rate*100:.2f}% (efectivo {e.effective_from})")
   ```
   If no events: "Sin cambios de tasa detectados en esta ejecución."

5. **Check institutions in DB**:
   ```python
   from rate_allocator.adapters.db_loader import load_institutions_from_db
   with session_scope(engine) as s:
       insts = load_institutions_from_db(s)
   for i in sorted(insts, key=lambda x: max(t.rate for t in x.tiers), reverse=True):
       print(f"  {i.name}: {max(t.rate for t in i.tiers):.2%}")
   ```

## Output format

```
[UPDATE-RATES] tasas.mx scraped — N institutions found
  [OK]   DiDi: 15.00%
  [OK]   Revolut: 15.00%
  ...
  [SKIP] <name>: not found on tasas.mx

[INGEST] scraped_live.yaml → DB
  batches_created: N
  tier_versions_inserted: N
  tier_versions_closed: N  ← non-zero means rates changed

[CHANGES DETECTED] (or [NO CHANGES])
  <institution> tramo N: X.XX% → Y.YY% (efectivo YYYY-MM-DD)

[DB SNAPSHOT] N institutions, sorted by top rate:
  DiDi: 15.00%
  Revolut: 15.00%
  ...
```

## Notes

- Tier **rates** come from tasas.mx (automated). Tier **limits** and **conditions** are manually
  curated in `src/rate_allocator/cli/scrape.py` → `TIER_STRUCTURES`. Update that dict when
  an institution restructures its product.
- If `bs4` is not installed: `pip install beautifulsoup4 requests`.
- If the scraper fails with "No table found", tasas.mx changed its HTML — update `fetch_rates()`
  in `src/rate_allocator/cli/scrape.py`.
- Rate changes detected by SCD2 appear automatically in the Streamlit "Noticias" section.
