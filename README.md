# lulu-basket

Finds up to 3 combinations of returnable (non-final-sale), in-stock lululemon.com (US) items whose pre-tax subtotal is at most a target (default $75.00) and as close to it as possible.

`scrape` crawls the site into a snapshot file; `solve` searches the snapshot offline; `run` does both.

## Install

Python 3.11+ and [uv](https://docs.astral.sh/uv/):

```
uv sync
```

## Usage

```
uv run lulu-basket scrape [--target CENTS] [--snapshot PATH] [--delay SECONDS]
uv run lulu-basket solve  [--target CENTS] [--snapshot PATH]
uv run lulu-basket run    [--target CENTS] [--snapshot PATH] [--delay SECONDS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--target CENTS` | `7500` | Subtotal limit in cents; a positive integer. |
| `--snapshot PATH` | `snapshot.json` | Snapshot file, relative to the current directory (gitignored). |
| `--delay SECONDS` | `1.0` | Pause before every request but the first; a number >= 0. `scrape` and `run` only. |

- `scrape` crawls the women's clothes, men's clothes and accessories catalogs and writes the snapshot. It keeps only SKUs in stock, not final sale, and priced at or below `--target`. The file is written only when the whole crawl succeeds; a failed scrape leaves the existing snapshot untouched.
- `solve` prints the top 3 combinations to stdout, or `No feasible combination.`. `--target` may be lower than the snapshot's target, never higher; for a higher one run `scrape --target <t>` again.
- `run` is `scrape` and then `solve` with the same options. If the scrape fails, nothing is printed to stdout.

Results go to stdout. Progress, warnings and errors (`error: <message>`) go to stderr.

```
Target $75.00 · snapshot 2026-10-06T12:00:00Z

#1  Total $75.00 ($0.00 below target)
  3 × Align High-Rise Pant 25"  $25.00 each  [stock cap 3: low-stock count]
      Black: 4, 6 · True Navy: 2
      https://shop.lululemon.com/p/...
```

Combinations are ranked by total (highest first), then fewest units. All units of one product bought at one price are the same color and size, so only colors and sizes with enough stock are listed.

## Snapshot

```json
{
  "schema": 1,
  "scraped_at": "2026-10-06T12:00:00Z",
  "target_cents": 7500,
  "skus": [
    {"product_id": "hnsjuvo8dn", "name": "Define Jacket *Nulu",
     "url": "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
     "color": "Black", "size": "4", "price_cents": 6800, "cap": null, "cap_source": null}
  ]
}
```

`price_cents` is the sale price if set, else the list price. `cap` is the inferred maximum units of that SKU per order, or `null` for no cap; `cap_source` is `"low_stock_count"` or `"low_stock_no_count"` when `cap` is set, else `null`. `solve` rejects a snapshot that does not match this schema.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success, including no feasible combination. |
| `1` | Scrape or solve failure (message on stderr). |
| `2` | Usage error. |

## Limits

- Stock caps are inferred from low-stock flags only: the number in `lowStockMessage` when present, else 1 for a low-stock SKU without a count. Real per-order limits are unknown.
- Sale-priced items have been observed to be final sale, so in practice they are excluded.
- Only the US site and the women's clothes, men's clothes and accessories catalogs are crawled (no shoes). Pre-tax subtotal only; no cart, tax or shipping.
- A full scrape fetches several hundred product pages and takes tens of minutes.
- Akamai may block the requests, and a site change may break parsing. Either way `scrape` fails with an error instead of printing results, after 3 attempts per page with waits of 5 s and 15 s.
- A product delisted mid-crawl aborts the scrape (rerun it). Live category ordering can make a crawl miss a product.
- Prices with a very small common step (for example 1 cent) make the search too large; `solve` then fails with `search space too large`.
