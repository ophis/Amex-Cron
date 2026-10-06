import unicodedata
from collections.abc import Sequence

from lulu_basket.snapshot import CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, Snapshot
from lulu_basket.solve.items import Item
from lulu_basket.solve.knapsack import Combination

_CAP_NOTES = {
    CAP_LOW_STOCK_COUNT: "low-stock count",
    CAP_LOW_STOCK_NO_COUNT: "low stock, no count",
}


def format_usd(cents: int) -> str:
    dollars, rest = divmod(cents, 100)
    return f"${dollars}.{rest:02d}"


def render(snapshot: Snapshot, target_cents: int, combos: Sequence[Combination]) -> str:
    lines = [f"Target {format_usd(target_cents)} · snapshot {_clean(snapshot.scraped_at)}", ""]
    if not combos:
        lines.append("No feasible combination.")
    for number, combo in enumerate(combos, 1):
        if number > 1:
            lines.append("")
        gap = format_usd(target_cents - combo.total_cents)
        lines.append(f"#{number}  Total {format_usd(combo.total_cents)} ({gap} below target)")
        for item, count in combo.picks:
            lines.extend(_pick_lines(item, count))
    return "\n".join(lines) + "\n"


def _pick_lines(item: Item, count: int) -> list[str]:
    head = f"  {count} × {_clean(item.name)}  {format_usd(item.price_cents)} each"
    if item.cap is not None and count == item.cap:
        head += f"  [stock cap {item.cap}: {_CAP_NOTES[item.cap_source]}]"
    return [head, f"      {_colors(item, count)}", f"      {_clean(item.url)}"]


def _colors(item: Item, count: int) -> str:
    sizes_by_color: dict[str, list[str]] = {}
    for sku in item.skus:
        if sku.cap is None or sku.cap >= count:
            sizes_by_color.setdefault(_clean(sku.color), []).append(_clean(sku.size))
    return " · ".join(f"{color}: {', '.join(sizes)}" for color, sizes in sizes_by_color.items())


def _clean(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
