# Spec: Lululemon basket filler CLI (TASK-192, P1)

Source: PRD `Product Design/2026-10-05-1433-TASK-168-lululemon-basket-filler.md` (ophis/private_docs), phase P1 = FR-1..FR-9 + NFR-1.
Site facts below were observed on 2026-10-06 (15 impersonated requests); samples live in `tests/fixtures/`.

## Goal

One local command returns up to 3 combinations of returnable (non-final-sale), in-stock lululemon.com (US) items whose pre-tax subtotal is ≤ the target (default 7500 cents) and as close to it as possible. Any scrape problem → error exit, never a wrong result.

Non-goals (PRD): cart/checkout automation, tax/shipping, non-US markets, headless-browser fallback, scheduling/alerts, filtering by category/size/color/preference, exclude-lists.

## Decisions (where this spec departs from or sharpens the PRD)

- **D1 Categories:** women = `/c/women-clothes/n14uwk`, men = `/c/men-clothes/n1oxc7`, accessories = `/c/accessories/n1dslk` (the homepage nav's top-level catalog pages; "Women"/"Men" nav links go to content pages). Shoes and the gendered accessory sub-catalogs are not crawled.
- **D2 Snapshot price:** each SKU's price comes from its product-page SKU `price` (`salePrice` if non-null, else `listPrice`). The PRD assumed product pages carry no price; they do, per SKU, and matched category color prices for all 464 overlapping in-stock SKUs. Category color prices are used only for the pre-filter (FR-1). This avoids joining SKUs to category colors.
- **D3 Low-stock warning:** `lowStockMessage` was null on all 886 observed SKUs, so in practice every low-stock SKU gets cap 1. The stderr warning is one aggregated line with the count, not one line per SKU.
- **D4 Output language:** all CLI output and messages are English (user rule: file contents stay English). The PRD's 「无可行组合」 is printed as `No feasible combination.`
- **D5 Colors/sizes shown:** for an item bought `n` times, only SKUs whose cap is unlimited or ≥ `n` are listed (PRD: same color and size within one combination).
- **D6 Strictness:** any non-200 response after retries (incl. 404 on a category continuation page or a product page) fails the scrape (FR-3), as do missing fields on any crawled product.
- Observed: `isFinalSale` == `price.onSale` on every SKU seen, so sale-priced items are in practice excluded as final sale. No code depends on this.

## Layout

Python ≥ 3.11 package managed with `uv`; `uv.lock` committed.

```
pyproject.toml            name lulu-basket; deps: curl_cffi; dev group: pytest; script lulu-basket = lulu_basket.cli:main
README.md                 usage, snapshot format, limits
src/lulu_basket/
  __main__.py             python -m lulu_basket
  cli.py                  argparse; scrape / solve / run
  errors.py               ToolError base; ScrapeError, SnapshotError, SolveError (cli maps ToolError → exit 1)
  snapshot.py             Snapshot + Sku dataclasses, atomic write, load + validate   (the only interface between layers)
  scrape/fetch.py         HTTP: curl_cffi session, delay, retries, block detection
  scrape/parse.py         __NEXT_DATA__ extraction; category-page and product-page parsing (pure)
  scrape/scrape.py        crawl, dedupe, pre-filter, SKU filter, caps, validation → Snapshot
  solve/items.py          SKUs → items (product + price), item caps
  solve/knapsack.py       top-3 bounded-knapsack search
  solve/report.py         text output
tests/                    pytest; never touches the network
```

**Layer rule (FR-4):** nothing under `lulu_basket/solve/` imports `lulu_basket.scrape` or `curl_cffi`, or names any site field; `lulu_basket.snapshot` and `lulu_basket.errors` are the only modules both layers share.

## CLI

`lulu-basket {scrape,solve,run} [--target CENTS] [--snapshot PATH] [--delay SECONDS]` (`--delay` on `scrape` and `run` only).

- `--target`: positive int cents, default `7500`.
- `--snapshot`: default `snapshot.json` (cwd); gitignored.
- `--delay`: seconds slept before every request but the first, default `1.0`, ≥ 0.
- Exit codes: `0` success (incl. no feasible combination); `1` scrape or solve failure; `2` usage error (argparse).
- Errors go to stderr as `error: <message>`; progress and warnings go to stderr; only `solve` results go to stdout.
- `run` = `scrape` then `solve` with the same `--target`/`--snapshot`; a failed `scrape` exits 1 before `solve` prints anything (FR-8).
- `cli.main(argv=None, *, http_get=None, sleep=time.sleep) -> int`; `http_get(url) -> (status, text)` replaces the real transport (tests inject fakes) and raises `fetch.TransportError` on a transport failure; the real adapter maps `curl_cffi` errors to it. `cli.main` is the only place that turns `ToolError` into exit 1. The console script exits with its return value.

## Scrape

### Site facts (paths from the root of `<script id="__NEXT_DATA__">`)

Let `Q(name)` = the entry of `props.pageProps.dehydratedState.queries[]` whose `queryKey[0] == name`; select by key, never by index.

Category page (`https://shop.lululemon.com<path>`, page N ≥ 2 adds `?page=N`, 40 products per page):
- `PAGE = Q("catalogPageData").state.data.pages[0]`
- `PAGE.data.attributes.totalCount` int; more pages exist iff `PAGE.data.relationships.products.links.next` is present and non-empty.
- Products: `PAGE.included[]` with `type == "products"`. Per product `P`: `P.id` (str), `P.attributes.name`, `P.attributes.url` (relative, e.g. `/p/define-jacket-nulu/hnsjuvo8dn`), `P.attributes.styles[].colors[]` each with `price.listPrice` (int dollars), optional `price.salePrice` (key absent when not on sale), `availability.isAvailable` (bool).
- Ordering is live; ids can repeat across pages.

Product page (`https://shop.lululemon.com` + `P.attributes.url`):
- `PDP = Q("pdp")` entry whose `queryKey[1] == product id` (pages also embed sibling products' `pdp` queries).
- SKUs: `PDP.state.data.skus[]`, each: `size` (str, e.g. `"4"`, `"ONE SIZE"`), `inseam` (str or null, e.g. `"28\""`), `color.name`, `available` (bool), `isFinalSale` (bool), `isLowStock` (bool or null), `lowStockMessage` (str or null), `price.listPrice` (str dollars), `price.salePrice` (str or null).

Blocked request: HTTP 403 from Akamai with body containing `Access Denied`, no `__NEXT_DATA__`.

### Fetch (`scrape/fetch.py`)

- One `curl_cffi.requests.Session(impersonate="chrome")` per scrape, timeout 30 s, TLS verification on, requests strictly sequential. Redirects are followed (slugs 301); a final URL not on `https://shop.lululemon.com` → `ScrapeError` `redirected off-site: <url>` (no retry).
- Sleep `delay` before each request except the first.
- Up to 4 attempts per URL, sleeping 5 s, 15 s, then 45 s between attempts. Retry on: transport error/timeout, HTTP 400, 403, 429, 5xx, or a 200 body containing `Access Denied` without `__NEXT_DATA__`. Any other non-200 (e.g. 404) fails at once.
- HTTP 400 is retried because the site intermittently answers a valid category page with 400 `{"message": "Bad Request.", "errorCode": "GE401001"}` and serves the same URL with 200 seconds later (observed 2026-10-06: 3 of 22 category pages on first try; not cookie- or session-related).
- Final failure raises `ScrapeError` (`lulu_basket.errors`): blocked (last attempt 403 or Access-Denied page) → `blocked by site after 4 attempts: <url>`; otherwise → `request failed: <HTTP status | error>: <url>`.

### Parse (`scrape/parse.py`, pure, raises `ScrapeError`)

- `extract_next_data(html, url) -> dict`: missing script or invalid JSON → `__NEXT_DATA__ not found: <url>`.
- `parse_price_cents(value, where) -> int`: int (not bool) dollars, or str matching `^\d+(\.\d{1,2})?$`, converted exactly (Decimal) to cents; anything else or ≤ 0 → `unparseable price <value!r>: <where>`.
- `parse_category_page(data, url)` → products + `has_next`. Required (else `missing field <path>: product <id or ?> on <url>`): the `catalogPageData` query and the `PAGE` path; per product `id`, `attributes.name`, `attributes.url` (str starting `/`), non-empty `attributes.styles`, each style non-empty `colors`, each color `price.listPrice` and `availability.isAvailable` (bool). Every color's price is parsed (`salePrice` if present and non-null, else `listPrice`). Each product yields `id`, `name`, absolute `url`, and `min_available_price_cents` = min price over colors with `isAvailable` true (None if none).
- `parse_product_page(data, product_id, url)` → SKU list. Missing `pdp` query for that id, or `skus` not a list → `missing field ...`. An empty list is allowed.

### Crawl and filter (`scrape/scrape.py`)

1. For each category in D1 order: fetch page 1, then `?page=2, 3, …` while `has_next`; abort with `pagination did not terminate: <url>` beyond `ceil(totalCount/40) + 2` pages (`totalCount` read from page 1). A category whose crawl stops after `n` pages with `n × 40 < totalCount − 40` → `pagination ended early: <url of page n>` (guards against a vanished `links.next` silently truncating the crawl; the 40-product slack absorbs live count drift).
2. Dedupe products by `id`, keeping first seen. Zero products → `no products found on category pages`.
3. Pre-filter: keep products with `min_available_price_cents` ≤ target, in first-seen order; fetch each product page.
4. Classify each SKU, first match wins, counting each reason:
   - `available` or `isFinalSale` not a bool → excluded: missing flag (FR-2);
   - `available` false → excluded: unavailable;
   - `isFinalSale` true → excluded: final sale;
   - otherwise require `color.name` and `size` (non-empty str) and parse its price (`salePrice` if non-null, else `listPrice`) → else FR-3 error; price > target → excluded: over target;
   - cap: `lowStockMessage` is a str containing digits → first integer (0 → excluded: unavailable), source `low_stock_count`; else `isLowStock is True` → cap 1, source `low_stock_no_count`; else no cap.
   - kept → snapshot SKU: `product_id`, `name` (category name), `url` (absolute product URL), `color` (`color.name`), `size` (`size`, plus ` / <inseam>` when inseam is non-null), `price_cents`, `cap`, `cap_source`.
5. Zero kept SKUs → log the `excluded SKUs:` line (step 6), then fail with `no eligible SKUs after filtering`.
6. stderr: progress (one line per category page, one per 25 product pages and at the end), a summary (products found, product pages fetched, SKUs kept) and one line `excluded SKUs: final sale <n>, unavailable <n>, missing flag <n>, over target <n>`; if any `low_stock_no_count` SKU: `warning: <n> low-stock SKUs have no count in lowStockMessage; capped at 1`.
7. Write the snapshot atomically (`tempfile.mkstemp` in the same dir + `os.replace`; the temp file is removed on failure). Any `OSError` or `ValueError` while writing → `SnapshotError` `cannot write snapshot <path>: <reason>`. On any `ScrapeError` nothing is written, so an existing snapshot is unchanged.

## Snapshot (`snapshot.py`), schema 1

```json
{
  "schema": 1,
  "scraped_at": "2026-10-06T12:00:00Z",
  "target_cents": 7500,
  "skus": [
    {"product_id": "hnsjuvo8dn", "name": "Define Jacket *Nulu", "url": "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
     "color": "Black", "size": "4", "price_cents": 6800, "cap": null, "cap_source": null}
  ]
}
```

- `cap`: positive int or null; `cap_source`: `"low_stock_count"` | `"low_stock_no_count"` when `cap` is set, null when not.
- `load_snapshot(path)` validates all of the above (`schema == 1`; `target_cents` positive int; string fields non-empty; `price_cents` positive int, bools rejected). Missing file → `snapshot not found: <path>; run scrape first`; any invalid content → `invalid snapshot <path>: <reason>`; both raise `SnapshotError` → exit 1.

## Solve

1. `target > snapshot.target_cents` → error `target <t> exceeds snapshot target <s>; re-run scrape --target <t>` (FR-6).
2. **Items** (`solve/items.py`): group SKUs with `price_cents ≤ target` by `(product_id, price_cents)`; name and url from the first SKU. Item cap: none if any SKU has no cap, else the max SKU cap, with that SKU's source (`low_stock_count` wins ties). Items sorted by `(product_id, price_cents)`.
3. **Search** (`solve/knapsack.py`): a combination assigns each item a count `0 ≤ n ≤ min(cap, target // price)`, not all zero, total ≤ target; all `n` units of an item are the same SKU (hence the item cap is a single SKU's cap). Distinct = different item→count maps. Order: total desc → total count asc → key asc, key = the tuple of `(product_id, price_cents, n)` over items with `n > 0` in item order, compared as Python tuples (a prefix sorts first). Return the first 3 (fewer if fewer exist).
   - Suggested algorithm: divide prices and target by `g = gcd(prices)`; with `T = target // g`, `K = T // min_price`, build suffix reachability sets over `(sum, count)` as Python-int bitsets (bit `sum*(K+1)+count`); then for `sum = T..1`, `count = 1..K` reachable from item 0, enumerate combinations by DFS (next item ascending, then count ascending) pruned by the suffix sets, stopping at 3. Memory is `O(items · T · K)` bits — fine for whole-dollar prices. Guard: `(T+1)·(K+1) > 1_000_000` → `SolveError` `search space too large (target <t>, price step <g> cents)`, exit 1.
4. **Report** (`solve/report.py`), stdout:
   ```
   Target $75.00 · snapshot 2026-10-06T12:00:00Z

   #1  Total $75.00 ($0.00 below target)
     3 × Align High-Rise Pant 25"  $25.00 each  [stock cap 3: low-stock count]
         Black: 4, 6 · True Navy: 2
         https://shop.lululemon.com/p/...
   ```
   Site-sourced strings are printed with control characters removed. Per item: count, name, unit price, cap note only when `n` equals a set item cap (`[stock cap <c>: low-stock count]` or `[stock cap <c>: low stock, no count]`), colors with their sizes per D5 (first-seen order), URL. Per combination: number, total, and `<gap> below target`. None → `No feasible combination.`, exit 0.

## Tests (`uv run pytest`, no network)

Fixtures: real trimmed `__NEXT_DATA__` samples (1 category page with 3 products, 3 product pages) wrapped into HTML at test time, plus small builders for synthetic cases. Fakes are injected through `http_get`/`sleep`; no product code is altered to force a branch.

- FR-1: fixture crawl → every snapshot SKU has name, color, size, int cents price, absolute URL, `cap` + `cap_source` (or both null); pagination follows `links.next`; dedupe fetches each product page once; pre-filter skips products whose cheapest available color > target.
- FR-2: SKUs final sale / unavailable / missing `isFinalSale` / missing `available` → only eligible SKUs in the snapshot; stderr shows each count.
- FR-3: one test per case — 403 after retries, Access-Denied 200 page, network error, 404, missing `__NEXT_DATA__`, each required field missing, zero products, bad price (category and SKU), zero eligible → exit 1, distinct message, pre-existing snapshot bytes unchanged. Retry count and waits asserted via the fake `sleep`.
- Caps: digits in `lowStockMessage` → that number; `isLowStock` true without digits → 1 + one warning line; `isLowStock` null/false → no cap.
- FR-4: a hand-written snapshot runs through `solve`; an AST scan of `lulu_basket/solve/*.py` finds no import of `lulu_basket.scrape` or `curl_cffi`.
- FR-5: the PRD cases exactly ({A 2500, B 3000} → 3×A, 2×B, A+B; A cap 2 → 2×B, A+B, 2×A; {A 8000} → `No feasible combination.`, exit 0), plus a brute-force cross-check of the top-3 order on random small instances (incl. caps and equal totals).
- FR-6: `--target 5000` → every total ≤ 5000; snapshot target 7500 + `--target 10000` → exit 1 with the re-scrape hint; `--target 0` / non-int → exit 2.
- FR-7: output contains number, name, colors/sizes, unit price, count, URL, total, gap; cap note for a cap-1 item bought once; D5 filtering.
- FR-8: `run` with a failing fake transport → exit 1, empty stdout.
- FR-9: `pyproject.toml` dependencies include `curl_cffi` and none of `scrapling`, `playwright`, `patchright`.
- NFR-1: 500 random items (whole-dollar prices $5–$75, ~20% capped 1–3), target 7500 → items + search < 100 ms (best of 3).
- Snapshot: round-trip; each invalid field → `SnapshotError`.
- Hardening: off-site redirect → `redirected off-site`; search-space guard → exit 1; control characters in names are stripped from output.

## P1 exit check (manual, real network)

`uv run lulu-basket run` prints combinations whose items are in stock, not final sale, and total ≤ $75 when checked on lululemon.com.

## Risks

- Akamai may start blocking `curl_cffi`; then `scrape` fails per FR-3.
- Several hundred product pages of 1–2 MB each: a run takes tens of minutes and may hit rate limits.
- Live category ordering can shift products across pages during a crawl, so a product can be missed.
- Stock caps are inferred from low-stock flags only; real per-order limits are unknown.
- One product delisted mid-crawl (404) aborts the whole scrape (D6); rerun.
- Transient 400s that outlast the ~65 s retry window fail the scrape; rerun.
