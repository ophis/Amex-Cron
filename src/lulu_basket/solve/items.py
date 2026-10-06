from collections.abc import Iterable
from dataclasses import dataclass

from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, Sku


@dataclass(frozen=True)
class Item:
    product_id: str
    name: str
    url: str
    price_cents: int
    cap: int | None
    cap_source: str | None
    skus: tuple[Sku, ...]


def build_items(skus: Iterable[Sku], target_cents: int) -> list[Item]:
    groups: dict[tuple[str, int], list[Sku]] = {}
    for sku in skus:
        if sku.price_cents <= target_cents:
            groups.setdefault((sku.product_id, sku.price_cents), []).append(sku)
    return [_item(*key, groups[key]) for key in sorted(groups)]


def _item(product_id: str, price_cents: int, group: list[Sku]) -> Item:
    if any(sku.cap is None for sku in group):
        cap, cap_source = None, None
    else:
        top = max(group, key=lambda sku: (sku.cap, sku.cap_source == CAP_LOW_STOCK_COUNT))
        cap, cap_source = top.cap, top.cap_source
    first = group[0]
    return Item(product_id, first.name, first.url, price_cents, cap, cap_source, tuple(group))
