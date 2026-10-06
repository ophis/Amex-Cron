import json
from pathlib import Path

import pytest

from lulu_basket.scrape.parse import BASE_URL

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return load


@pytest.fixture
def next_data_html():
    def wrap(data: dict) -> str:
        return (
            "<html><body>"
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
            "</body></html>"
        )

    return wrap


CATEGORY_PATHS = ("/c/women-clothes/n14uwk", "/c/men-clothes/n1oxc7", "/c/accessories/n1dslk")


class FakeSite:
    """Serves pages by URL (unknown URLs answer 404) and records every request."""

    def __init__(self, wrap):
        self._wrap = wrap
        self.responses: dict[str, tuple[int, str]] = {}
        self.requests: list[str] = []
        for path in CATEGORY_PATHS:
            self.add_category(path, [[]])

    def http_get(self, url: str) -> tuple[int, str]:
        self.requests.append(url)
        return self.responses.get(url, (404, "Not Found"))

    def add_page(self, url: str, data: dict) -> None:
        self.responses[url] = (200, self._wrap(data))

    @staticmethod
    def product(product_id: str, name: str = "Product", colors=((50, True),)) -> dict:
        """A category-page product; colors are (list price in dollars, available) pairs."""
        return {
            "id": product_id,
            "type": "products",
            "attributes": {
                "name": name,
                "url": f"/p/item/{product_id}",
                "styles": [
                    {
                        "id": "S1",
                        "colors": [
                            {
                                "id": f"S1-C{i}",
                                "price": {"listPrice": price},
                                "availability": {"isAvailable": available},
                            }
                            for i, (price, available) in enumerate(colors)
                        ],
                    }
                ],
            },
        }

    def add_category(self, path: str, pages: list[list[dict]], total_count: int | None = None):
        """Page N lists pages[N-1]; every page but the last links to the next one."""
        total = 40 * len(pages) if total_count is None else total_count
        for number, products in enumerate(pages, start=1):
            links = {"self": f"/v1/page{number}"}
            if number < len(pages):
                links["next"] = f"/v1/page{number + 1}"
            page = {
                "data": {
                    "attributes": {"totalCount": total},
                    "relationships": {"products": {"links": links}},
                },
                "included": [{"id": "cat", "type": "category-page-data"}, *products],
            }
            query = {
                "queryKey": ["catalogPageData", "cdp", {"hash": "cat"}],
                "state": {"data": {"pages": [page]}},
            }
            url = BASE_URL + path + ("" if number == 1 else f"?page={number}")
            self.add_page(url, {"props": {"pageProps": {"dehydratedState": {"queries": [query]}}}})

    def add_product(self, product: dict, skus: list) -> None:
        query = {
            "queryKey": ["pdp", product["id"], "v1", "en-us"],
            "state": {"data": {"skus": skus}},
        }
        url = BASE_URL + product["attributes"]["url"]
        self.add_page(url, {"props": {"pageProps": {"dehydratedState": {"queries": [query]}}}})


@pytest.fixture
def fake_site(next_data_html):
    return FakeSite(next_data_html)
