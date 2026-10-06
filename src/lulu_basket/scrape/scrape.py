import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil

from lulu_basket.errors import ScrapeError
from lulu_basket.scrape.fetch import Fetcher
from lulu_basket.scrape.parse import (
    BASE_URL,
    CategoryPage,
    CategoryProduct,
    extract_next_data,
    parse_category_page,
    parse_price_cents,
    parse_product_page,
)
from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, Sku, Snapshot

CATEGORIES = (
    ("women-clothes", "/c/women-clothes/n14uwk"),
    ("men-clothes", "/c/men-clothes/n1oxc7"),
    ("accessories", "/c/accessories/n1dslk"),
)

PAGE_SIZE = 40
EXTRA_PAGES = 2
PROGRESS_EVERY = 25

_FINAL_SALE = "final sale"
_UNAVAILABLE = "unavailable"
_MISSING_FLAG = "missing flag"
_OVER_TARGET = "over target"
_EXCLUSION_ORDER = (_FINAL_SALE, _UNAVAILABLE, _MISSING_FLAG, _OVER_TARGET)
_DIGITS = re.compile(r"[0-9]+")


def scrape(target_cents: int, fetcher: Fetcher, log: Callable[[str], None]) -> Snapshot:
    products = _crawl_categories(fetcher, log)
    if not products:
        raise ScrapeError("no products found on category pages")

    wanted = [
        p
        for p in products.values()
        if p.min_available_price_cents is not None and p.min_available_price_cents <= target_cents
    ]
    excluded: Counter[str] = Counter()
    skus: list[Sku] = []
    for number, product in enumerate(wanted, start=1):
        url = product.url
        data = extract_next_data(fetcher.get(url), url)
        raw_skus = parse_product_page(data, product.id, url)
        skus.extend(_keep_eligible(product, raw_skus, target_cents, excluded))
        if number % PROGRESS_EVERY == 0 or number == len(wanted):
            log(f"product pages {number}/{len(wanted)}")
    if not skus:
        raise ScrapeError("no eligible SKUs after filtering")

    log(
        f"products found {len(products)}, product pages fetched {len(wanted)}, "
        f"SKUs kept {len(skus)}"
    )
    counts = ", ".join(f"{reason} {excluded[reason]}" for reason in _EXCLUSION_ORDER)
    log(f"excluded SKUs: {counts}")
    uncounted = sum(1 for s in skus if s.cap_source == CAP_LOW_STOCK_NO_COUNT)
    if uncounted:
        log(f"warning: {uncounted} low-stock SKUs have no count in lowStockMessage; capped at 1")
    return Snapshot(_utc_now(), target_cents, tuple(skus))


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _crawl_categories(fetcher: Fetcher, log: Callable[[str], None]) -> dict[str, CategoryProduct]:
    products: dict[str, CategoryProduct] = {}
    for name, path in CATEGORIES:
        first_url = BASE_URL + path
        page = _fetch_category_page(fetcher, first_url)
        expected = ceil(page.total_count / PAGE_SIZE)
        number = 1
        while True:
            log(f"{name} page {number}/{expected}: {len(page.products)} listed")
            for product in page.products:
                products.setdefault(product.id, product)
            if not page.has_next:
                break
            number += 1
            url = f"{first_url}?page={number}"
            if number > expected + EXTRA_PAGES:
                raise ScrapeError(f"pagination did not terminate: {url}")
            page = _fetch_category_page(fetcher, url)
    return products


def _fetch_category_page(fetcher: Fetcher, url: str) -> CategoryPage:
    return parse_category_page(extract_next_data(fetcher.get(url), url), url)


def _keep_eligible(
    product: CategoryProduct, raw_skus: list, target_cents: int, excluded: Counter[str]
) -> list[Sku]:
    kept = []
    for index, raw in enumerate(raw_skus):
        if not isinstance(raw, dict):
            raise _missing(f"skus[{index}]", product)
        available, final_sale = raw.get("available"), raw.get("isFinalSale")
        if not isinstance(available, bool) or not isinstance(final_sale, bool):
            excluded[_MISSING_FLAG] += 1
            continue
        if not available:
            excluded[_UNAVAILABLE] += 1
            continue
        if final_sale:
            excluded[_FINAL_SALE] += 1
            continue

        color = raw.get("color")
        color_name = color.get("name") if isinstance(color, dict) else None
        if not isinstance(color_name, str) or not color_name:
            raise _missing(f"skus[{index}].color.name", product)
        size = raw.get("size")
        if not isinstance(size, str) or not size:
            raise _missing(f"skus[{index}].size", product)
        price = raw.get("price")
        price = price if isinstance(price, dict) else {}
        sale_price = price.get("salePrice")
        price_cents = parse_price_cents(
            price.get("listPrice") if sale_price is None else sale_price,
            f"product {product.id} skus[{index}] on {product.url}",
        )
        if price_cents > target_cents:
            excluded[_OVER_TARGET] += 1
            continue

        cap, cap_source = _cap(raw)
        if cap == 0:
            excluded[_UNAVAILABLE] += 1
            continue
        inseam = raw.get("inseam")
        kept.append(
            Sku(
                product_id=product.id,
                name=product.name,
                url=product.url,
                color=color_name,
                size=size if inseam is None else f"{size} / {inseam}",
                price_cents=price_cents,
                cap=cap,
                cap_source=cap_source,
            )
        )
    return kept


def _cap(raw: dict) -> tuple[int | None, str | None]:
    message = raw.get("lowStockMessage")
    count = _DIGITS.search(message) if isinstance(message, str) else None
    if count:
        return int(count.group()), CAP_LOW_STOCK_COUNT
    if raw.get("isLowStock") is True:
        return 1, CAP_LOW_STOCK_NO_COUNT
    return None, None


def _missing(path: str, product: CategoryProduct) -> ScrapeError:
    return ScrapeError(f"missing field {path}: product {product.id} on {product.url}")
