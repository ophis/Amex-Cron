# Plan: Lululemon basket filler (TASK-192, P1)

Requirement: TASK-192 build input (PRD `Product Design/2026-10-05-1433-TASK-168-lululemon-basket-filler.md`, phase P1).

RESUME: phase=S7 worktree=/Users/francis/.agent-pm/work/TASK-192/src/ophis/Amex-Cron branch=TASK-192-lululemon base_ref=f3596732635451aeca1e8274d8d4d5670c7ef86c review_round=0 spec_file=/Users/francis/.agent-pm/work/TASK-192/src/ophis/Amex-Cron/docs/.autopilot/2026-10-06-lululemon-basket-filler-spec.md

## Progress

- S1: reused agent-pm worktree (branch TASK-192-lululemon, base f359673).
- S2: live probe of shop.lululemon.com (15 requests) fixed JSON paths and category URLs; spec written.
- decision(price source): SKU price from product-page SKU price over category color price - per-SKU, no color join; dissent: none
- decision(output language): English CLI output over PRD's Chinese message - user rule: file contents English; dissent: none
- S3 panel: core=[architecture,spec-fitness] +optional=[security] transport=Workflow
- S3 r0: architecture=PASS spec-fitness=PASS security=PASS -> converged; folded non-blockers: TransportError contract, errors module, search-space guard, same-SKU rule, prefix order, totalCount from page 1, off-site redirect check, control-char stripping, mkstemp temp file, risks (404 mid-crawl, session reuse)
- decision(non-blockers skipped): no response-size cap, no price upper bound - local single-user tool, prices > target are dropped anyway; dissent: none
- S5: 7 tasks done via SDD, each task-reviewed clean (commits 28daddc..6f13385); deferred minors kept in SDD ledger for S7
- S6: `uv run pytest` 618 passed; CLI help smoke ok; live `run` started in background (P1 exit check)
- S6 live run 1: exit 1 `request failed: HTTP 400: …women-clothes…?page=15` (fail-safe held). Reproduced: transient per-page 400 `GE401001`, same URL 200 seconds later; not cookie/session (fails with cleared cookies and fresh sessions too).
- decision(transient 400): retry HTTP 400 and widen backoff to 4 attempts (5/15/45 s) over failing fast - the 400s are transient, failing fast made the tool unusable; spec Fetch updated; dissent: none
- S7 panel: core=[correctness,requirement-fidelity,doc] +optional=[architecture,code-quality,performance,test] transport=Workflow
- S6 fix: d552959 retries 400 (4 attempts, 5/15/45 s); `uv run pytest` 620 passed; live run 2 started
- S7 r0: correctness=PASS requirement-fidelity=PASS doc=PASS architecture=PASS code-quality=PASS performance=PASS test=PASS -> no blockers; non-blockers raised by 3 lenses: pagination can end early silently (missing links.next), zero-eligible error hides exclusion counts; P1 live exit check not yet met
- S6 live run 2: exit 1 at women-clothes ?page=13, 400 on all 4 attempts. 400 JSON served by AkamaiGHost; same URL recovered after ~30 s idle -> edge rate throttling, not a page fault. Measuring onset at 4 s pacing.
- S6 live: after run 2, a 2-min cooldown still gave 400 on category pages, and product page + homepage also 400 (03:12 EDT) -> client-wide penalty; live traffic paused. Open question: rate-based (pacing fixes it) vs request-count bot detection (needs a browser, PRD risk).
- S7 fix 1 (pre-fix HEAD bc82799): fresh producer a7d455d3467a68114 for adopted non-blockers correctness#1,#2,#4 / requirement-fidelity#2,#3 / architecture#4,#6 / code-quality#3 + Task 6/7 minors (inseam, price message, test gaps, README sample)

## Implementation plan

Spec: `docs/.autopilot/2026-10-06-lululemon-basket-filler-spec.md` (binding; the tasks below argue from it).

### Global Constraints

- Worktree `/Users/francis/.agent-pm/work/TASK-192/src/ophis/Amex-Cron`, branch `TASK-192-lululemon`; absolute paths / `git -C`; before any write assert `git -C <worktree> branch --show-current` is `TASK-192-lululemon`. Create no other clone, worktree or branch; never touch `main`.
- After each task's commit run exactly `git -C /Users/francis/.agent-pm/work/TASK-192/src/ophis/Amex-Cron push -u origin TASK-192-lululemon`.
- Python ≥ 3.11, `uv`-managed; package `lulu_basket` under `src/`; runtime dependency `curl_cffi` only; dev group `pytest`. Verify command: `uv run pytest` (from the worktree, e.g. `uv run --directory <worktree> pytest`).
- Tests never touch the network; fakes enter through `http_get` / `sleep` parameters.
- **No mutation testing:** never substitute a known-wrong value into existing code to force a branch or fail a test, by any route (edit, runtime reassignment), not even briefly. A test's red step is its failure before its code exists. To test a guard, call it; to fake the environment, inject a fake or patch a stdlib call.
- All code, comments, messages, docs in English; comments only for a non-obvious reason. Error messages are exactly the spec's strings.
- Layer rule: nothing under `src/lulu_basket/solve/` imports `lulu_basket.scrape` or `curl_cffi`.
- TDD: write each listed test first, see it fail, then implement.

### Task 1: Project scaffold, errors, snapshot

- Files: `pyproject.toml`, `uv.lock`, `.gitignore` (append `snapshot.json`, `.venv/`, `.pytest_cache/`), `src/lulu_basket/__init__.py`, `src/lulu_basket/errors.py`, `src/lulu_basket/snapshot.py`, `tests/test_snapshot.py`, `tests/test_dependencies.py`.
- `pyproject.toml`: project `lulu-basket`, `requires-python = ">=3.11"`, `dependencies = ["curl_cffi>=0.7"]`, `[project.scripts] lulu-basket = "lulu_basket.cli:main"`, `[dependency-groups] dev = ["pytest>=8"]`, hatchling build with `src/` layout, pytest `testpaths = ["tests"]`. Run `uv lock`.
- Produces:
  - `errors.ToolError(Exception)`; subclasses `ScrapeError`, `SnapshotError`, `SolveError`.
  - `snapshot.CAP_LOW_STOCK_COUNT = "low_stock_count"`, `snapshot.CAP_LOW_STOCK_NO_COUNT = "low_stock_no_count"`.
  - frozen dataclass `snapshot.Sku(product_id: str, name: str, url: str, color: str, size: str, price_cents: int, cap: int | None, cap_source: str | None)`.
  - frozen dataclass `snapshot.Snapshot(scraped_at: str, target_cents: int, skus: tuple[Sku, ...])`.
  - `snapshot.write_snapshot(path: str | os.PathLike, snap: Snapshot) -> None` — JSON per spec schema 1, atomic via `tempfile.mkstemp` in the target dir + `os.replace`, temp removed on failure.
  - `snapshot.load_snapshot(path) -> Snapshot` — validates per spec; raises `SnapshotError` with `snapshot not found: <path>; run scrape first` or `invalid snapshot <path>: <reason>`.
- Tests first: round-trip; missing file; non-JSON; `schema != 1`; `target_cents` 0 / negative / bool / str; each string field empty or non-str; `price_cents` 0 / bool / float; `cap` 0 / negative; `cap` set with `cap_source` null or unknown; `cap` null with `cap_source` set; write leaves no temp file behind. FR-9: `pyproject.toml` (parsed with `tomllib`) dependencies include `curl_cffi`, none of `scrapling`, `playwright`, `patchright`.
- Commit: `Add project scaffold and snapshot interface`

### Task 2: Items and top-3 search

- Files: `src/lulu_basket/solve/__init__.py`, `src/lulu_basket/solve/items.py`, `src/lulu_basket/solve/knapsack.py`, `tests/test_items.py`, `tests/test_knapsack.py`.
- Consumes: `snapshot.Sku`, `snapshot.CAP_*`, `errors.SolveError`.
- Produces:
  - frozen dataclass `items.Item(product_id: str, name: str, url: str, price_cents: int, cap: int | None, cap_source: str | None, skus: tuple[Sku, ...])`.
  - `items.build_items(skus: Iterable[Sku], target_cents: int) -> list[Item]` — spec Solve step 2 (drop price > target; group by `(product_id, price_cents)`; cap none if any SKU uncapped else max with that SKU's source, `low_stock_count` wins ties; sorted by `(product_id, price_cents)`).
  - frozen dataclass `knapsack.Combination(total_cents: int, picks: tuple[tuple[Item, int], ...])` (picks in item order, counts ≥ 1).
  - `knapsack.top_combinations(items: Sequence[Item], target_cents: int, limit: int = 3) -> list[Combination]` — spec Solve step 3 order and guard (`(T+1)·(K+1) > 1_000_000` → `SolveError` `search space too large (target <t>, price step <g> cents)`).
- Tests first: PRD FR-5 cases exactly ({A 2500, B 3000}, target 7500 → 3×A 7500, 2×B 6000, A+B 5500; A cap 2 → 2×B, A+B, 2×A; {A 8000} → `[]`); fewer than 3 combinations → all; count tie-break (equal totals, fewer units first); key tie-break (equal totals and counts, lexicographic by `(product_id, price_cents, n)`, prefix first); caps respected; brute-force cross-check against exhaustive enumeration on ≥ 200 seeded random instances (2–6 items, prices 100–4000 cents incl. non-multiples of 100, random caps, target 1000–7500); guard raises `SolveError`; NFR-1: 500 random items (seeded, whole-dollar $5–$75, ~20 % capped 1–3), target 7500 → `build_items` + `top_combinations` best-of-3 < 100 ms. Items: grouping, cap rules, tie source, price > target dropped, order.
- Commit: `Add bounded-knapsack top-3 search`

### Task 3: Report

- Files: `src/lulu_basket/solve/report.py`, `tests/test_report.py`.
- Consumes: `Snapshot`, `Item`, `Combination`.
- Produces: `report.format_usd(cents: int) -> str` (`7500` → `$75.00`); `report.render(snapshot: Snapshot, target_cents: int, combos: Sequence[Combination]) -> str` — exact layout from spec Solve step 4: header `Target $75.00 · snapshot <scraped_at>`, blank line, per combination `#<i>  Total $<t> ($<gap> below target)`, per pick `  <n> × <name>  $<price> each` + cap note `  [stock cap <c>: low-stock count]` / `  [stock cap <c>: low stock, no count]` only when `n == item.cap`, then `      <color>: <size>, <size> · <color>: …` listing only SKUs with cap None or ≥ n, grouped by color in first-seen order, then `      <url>`; blank line between combinations; empty combos → `No feasible combination.` after the header. Control characters (Unicode category `Cc`) are removed from every site-sourced string.
- Tests first: all FR-7 fields present; gap math; cap note for a cap-1 item bought once, both sources, absent when `n < cap`; D5 SKU filtering; color grouping order; `No feasible combination.`; control characters stripped.
- Commit: `Add solve report formatting`

### Task 4: Page parsing

- Files: `src/lulu_basket/scrape/__init__.py`, `src/lulu_basket/scrape/parse.py`, `tests/fixtures/category.json`, `tests/fixtures/product_define_jacket.json`, `tests/fixtures/product_align_pant.json`, `tests/fixtures/product_crossbody_bag.json` (copy verbatim from `/Users/francis/.agent-pm/work/TASK-192/tmp/probe.t30Z/samples/`), `tests/conftest.py` (helper wrapping a dict into `<script id="__NEXT_DATA__" type="application/json">…</script>` HTML), `tests/test_parse.py`.
- Consumes: `errors.ScrapeError`.
- Produces:
  - `parse.BASE_URL = "https://shop.lululemon.com"`.
  - `parse.extract_next_data(html: str, url: str) -> dict`.
  - `parse.parse_price_cents(value: object, where: str) -> int`.
  - frozen dataclass `parse.CategoryProduct(id: str, name: str, url: str, min_available_price_cents: int | None)` (`url` absolute).
  - frozen dataclass `parse.CategoryPage(products: tuple[CategoryProduct, ...], has_next: bool, total_count: int)`.
  - `parse.parse_category_page(data: dict, url: str) -> CategoryPage`.
  - `parse.parse_product_page(data: dict, product_id: str, url: str) -> list[dict]` (raw SKU dicts).
  - Messages exactly per spec Parse section.
- Tests first: real fixtures parse (3 products, ids/names/urls, min available price, `has_next`, `total_count`; product SKUs selected by product id when sibling `pdp` queries exist — fixture `product_align_pant.json` has siblings); `salePrice` absent / present / null; prices int, `"128"`, `"12.5"`, `"12.50"`; rejected: bool, `"12.345"`, `"-1"`, `"0"`, `0`, None, float; each required field missing → `missing field <path>`; missing script / bad JSON; missing `catalogPageData`; missing `pdp` for the id; `skus` not a list; empty `skus` → `[]`.
- Commit: `Add __NEXT_DATA__ page parsing`

### Task 5: Fetcher

- Files: `src/lulu_basket/scrape/fetch.py`, `tests/test_fetch.py`.
- Consumes: `errors.ScrapeError`, `parse.BASE_URL`.
- Produces:
  - `fetch.TransportError(Exception)`.
  - `fetch.HttpGet = Callable[[str], tuple[int, str]]`.
  - `fetch.curl_http_get() -> HttpGet` — one `curl_cffi.requests.Session(impersonate="chrome")`, `timeout=30`, redirects followed, TLS verify on; final URL not under `https://shop.lululemon.com` → `ScrapeError` `redirected off-site: <url>`; `curl_cffi` request errors → `TransportError`.
  - `fetch.Fetcher(http_get: HttpGet, sleep: Callable[[float], None], delay: float)` with `.get(url: str) -> str` — spec Fetch rules: sleep `delay` before every request but the first; 3 attempts; waits `5` then `15` s; retry on `TransportError`, 403, 429, 5xx, 200 + `Access Denied` without `__NEXT_DATA__`; other non-200 fails at once; messages `blocked by site after 3 attempts: <url>` / `request failed: <HTTP status | error>: <url>`.
- Tests first (fake `http_get`, recording fake `sleep`): first request no delay, later ones `delay`; 403×3 → blocked + sleeps `[5, 15]`; Access-Denied 200×3 → blocked; 403 then 200 → success; TransportError×3 → `request failed: <error>`; 500×3 → `request failed: HTTP 500`; 404 → immediate failure, no retry sleeps; off-site check via `curl_http_get` with `curl_cffi.requests.Session.get` patched to return a response whose `url` is off-site (no network).
- Commit: `Add rate-limited fetcher with retries`

### Task 6: Crawl, filter, caps

- Files: `src/lulu_basket/scrape/scrape.py`, `tests/test_scrape.py` (with a fake-site builder, may live in `tests/conftest.py`).
- Consumes: `Fetcher`, `parse.*`, `snapshot.Sku/Snapshot/CAP_*`, `errors.ScrapeError`.
- Produces:
  - `scrape.CATEGORIES = (("women-clothes", "/c/women-clothes/n14uwk"), ("men-clothes", "/c/men-clothes/n1oxc7"), ("accessories", "/c/accessories/n1dslk"))`.
  - `scrape.scrape(target_cents: int, fetcher: Fetcher, log: Callable[[str], None]) -> Snapshot` — spec Crawl and filter steps 1–6 (step 7's write is the CLI's); `scraped_at` = UTC ISO 8601 with `Z`, seconds precision; stderr lines via `log`, exact texts from spec step 6.
- Tests first (fake site: URL → HTML built from fixtures and builders): pagination follows `links.next` with `?page=N`, stops when absent; runaway pagination → `pagination did not terminate`; dedupe across categories → one product-page request; pre-filter by cheapest available color; SKU classification order and counts (missing flag, unavailable, final sale, over target) printed in the `excluded SKUs:` line; caps (`"Only 2 left"` → 2 `low_stock_count`; `isLowStock` true + null message → 1 `low_stock_no_count` + one aggregated warning; `"0 left"` → excluded unavailable; `isLowStock` null/false → no cap); size with inseam `4 / 28"`; kept SKU missing `color.name` / `size` / bad price → `ScrapeError`; zero products; zero eligible; every FR-1 record field present.
- Commit: `Add catalog crawl and SKU filtering`

### Task 7: CLI, run, README

- Files: `src/lulu_basket/cli.py`, `src/lulu_basket/__main__.py`, `README.md`, `tests/test_cli.py`, `tests/test_layering.py`.
- Consumes: everything above.
- Produces: `cli.main(argv: list[str] | None = None, *, http_get: HttpGet | None = None, sleep: Callable[[float], None] = time.sleep) -> int` — subcommands `scrape` / `solve` / `run`, options per spec CLI (`--target` positive int default 7500 → argparse error exit 2 otherwise; `--snapshot` default `snapshot.json`; `--delay` float ≥ 0 default 1.0 on scrape/run); `http_get` None → `curl_http_get()`; scrape writes the snapshot only on success; solve: `load_snapshot`, `target > snapshot.target_cents` → `SolveError` `target <t> exceeds snapshot target <s>; re-run scrape --target <t>`, then `build_items` → `top_combinations` → `render` to stdout; every `ToolError` → `error: <message>` on stderr, return 1. `__main__.py` → `raise SystemExit(main())`. README: what it does, install (`uv sync`), usage of the 3 commands with options, snapshot schema, exit codes, limits (stock caps inferred, sale items are final sale in practice, run takes tens of minutes, network/Akamai failure modes).
- Tests first: FR-3 end-to-end via `main` with fake `http_get` for each failure case (403, Access-Denied page, transport error, 404, missing `__NEXT_DATA__`, missing field, zero products, bad price, zero eligible) → return 1, distinct stderr message, pre-existing snapshot bytes unchanged; successful scrape writes a loadable snapshot; FR-4: hand-written snapshot JSON → `solve` stdout; FR-5 `{A 8000}` → `No feasible combination.` exit 0; FR-6 `--target 5000` totals ≤ 5000, `--target 10000` vs 7500 snapshot → 1 + re-scrape hint, `--target 0` / `abc` → 2; FR-8 `run` with failing fake → 1 and empty stdout; `run` success prints combinations; missing snapshot → 1; search-space guard → 1. Layering: AST scan of `src/lulu_basket/solve/*.py` finds no import of `lulu_basket.scrape` or `curl_cffi`.
- Commit: `Add CLI and README`
