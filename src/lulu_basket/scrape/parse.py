import json
import re
from dataclasses import dataclass
from decimal import Decimal

from lulu_basket.errors import ScrapeError

BASE_URL = "https://shop.lululemon.com"

_NEXT_DATA = re.compile(r'<script\b[^>]*\sid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
# fullmatch, not match: "$" would accept a trailing newline.
_PRICE = re.compile(r"[0-9]+(\.[0-9]{1,2})?")
_QUERIES = "dehydratedState.queries"
_PAGE = f"{_QUERIES}[catalogPageData].state.data.pages[0]"


@dataclass(frozen=True)
class CategoryProduct:
    id: str
    name: str
    url: str
    min_available_price_cents: int | None


@dataclass(frozen=True)
class CategoryPage:
    products: tuple[CategoryProduct, ...]
    has_next: bool
    total_count: int


def extract_next_data(html: str, url: str) -> dict:
    match = _NEXT_DATA.search(html)
    try:
        data = json.loads(match.group(1)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ScrapeError(f"__NEXT_DATA__ not found: {url}")
    return data


def parse_price_cents(value: object, where: str) -> int:
    dollars = None
    if isinstance(value, int) and not isinstance(value, bool):
        dollars = Decimal(value)
    elif isinstance(value, str) and _PRICE.fullmatch(value):
        dollars = Decimal(value)
    if dollars is None or dollars <= 0:
        raise ScrapeError(f"unparseable price {value!r}: {where}")
    return int(dollars * 100)


def parse_category_page(data: dict, url: str) -> CategoryPage:
    query = _find_query(data, "catalogPageData")
    if query is None:
        raise _page_missing(f"{_QUERIES}[catalogPageData]", url)
    pages = _get(query, "state", "data", "pages")
    page = pages[0] if isinstance(pages, list) and pages else None
    if not isinstance(page, dict):
        raise _page_missing(_PAGE, url)
    total_count = _get(page, "data", "attributes", "totalCount")
    if not isinstance(total_count, int) or isinstance(total_count, bool):
        raise _page_missing(f"{_PAGE}.data.attributes.totalCount", url)
    included = page.get("included")
    if not isinstance(included, list):
        raise _page_missing(f"{_PAGE}.included", url)
    products = tuple(
        _parse_product(entry, url)
        for entry in included
        if isinstance(entry, dict) and entry.get("type") == "products"
    )
    next_link = _get(page, "data", "relationships", "products", "links", "next")
    return CategoryPage(products, isinstance(next_link, str) and next_link != "", total_count)


def parse_product_page(data: dict, product_id: str, url: str) -> list[dict]:
    path = f"{_QUERIES}[pdp:{product_id}]"
    query = _find_query(data, "pdp", product_id)
    if query is None:
        raise _page_missing(path, url)
    skus = _get(query, "state", "data", "skus")
    if not isinstance(skus, list):
        raise _page_missing(f"{path}.state.data.skus", url)
    return skus


def _get(obj: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _find_query(data: dict, name: str, product_id: str | None = None) -> object:
    queries = _get(data, "props", "pageProps", "dehydratedState", "queries")
    if not isinstance(queries, list):
        return None
    for query in queries:
        key = _get(query, "queryKey")
        if not (isinstance(key, list) and key and key[0] == name):
            continue
        if product_id is None or (len(key) > 1 and key[1] == product_id):
            return query
    return None


def _page_missing(path: str, url: str) -> ScrapeError:
    return ScrapeError(f"missing field {path}: {url}")


def _product_missing(path: str, product_id: str | None, url: str) -> ScrapeError:
    return ScrapeError(f"missing field {path}: product {product_id or '?'} on {url}")


def _parse_product(entry: dict, url: str) -> CategoryProduct:
    product_id = entry.get("id")
    if not isinstance(product_id, str) or not product_id:
        raise _product_missing("id", None, url)
    name = _get(entry, "attributes", "name")
    if not isinstance(name, str) or not name:
        raise _product_missing("attributes.name", product_id, url)
    path = _get(entry, "attributes", "url")
    if not isinstance(path, str) or not path.startswith("/"):
        raise _product_missing("attributes.url", product_id, url)
    styles = _get(entry, "attributes", "styles")
    if not isinstance(styles, list) or not styles:
        raise _product_missing("attributes.styles", product_id, url)

    available_prices = []
    for style_index, style in enumerate(styles):
        colors_path = f"attributes.styles[{style_index}].colors"
        colors = _get(style, "colors")
        if not isinstance(colors, list) or not colors:
            raise _product_missing(colors_path, product_id, url)
        for color_index, color in enumerate(colors):
            color_path = f"{colors_path}[{color_index}]"
            list_price = _get(color, "price", "listPrice")
            if list_price is None:
                raise _product_missing(f"{color_path}.price.listPrice", product_id, url)
            is_available = _get(color, "availability", "isAvailable")
            if not isinstance(is_available, bool):
                raise _product_missing(f"{color_path}.availability.isAvailable", product_id, url)
            sale_price = _get(color, "price", "salePrice")
            color_id = _get(color, "id") or color_path
            cents = parse_price_cents(
                list_price if sale_price is None else sale_price,
                f"product {product_id} color {color_id} on {url}",
            )
            if is_available:
                available_prices.append(cents)

    return CategoryProduct(
        id=product_id,
        name=name,
        url=BASE_URL + path,
        min_available_price_cents=min(available_prices, default=None),
    )
