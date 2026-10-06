import contextlib
import json
import os
import tempfile
from dataclasses import dataclass

from lulu_basket.errors import SnapshotError

SCHEMA = 1
CAP_LOW_STOCK_COUNT = "low_stock_count"
CAP_LOW_STOCK_NO_COUNT = "low_stock_no_count"
_CAP_SOURCES = (CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT)
_SKU_STRING_FIELDS = ("product_id", "name", "url", "color", "size")


@dataclass(frozen=True)
class Sku:
    product_id: str
    name: str
    url: str
    color: str
    size: str
    price_cents: int
    cap: int | None
    cap_source: str | None


@dataclass(frozen=True)
class Snapshot:
    scraped_at: str
    target_cents: int
    skus: tuple[Sku, ...]


def write_snapshot(path: str | os.PathLike, snap: Snapshot) -> None:
    doc = {
        "schema": SCHEMA,
        "scraped_at": snap.scraped_at,
        "target_cents": snap.target_cents,
        "skus": [
            {
                "product_id": s.product_id,
                "name": s.name,
                "url": s.url,
                "color": s.color,
                "size": s.size,
                "price_cents": s.price_cents,
                "cap": s.cap,
                "cap_source": s.cap_source,
            }
            for s in snap.skus
        ],
    }
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def load_snapshot(path: str | os.PathLike) -> Snapshot:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        raise SnapshotError(f"snapshot not found: {path}; run scrape first") from None
    except (OSError, ValueError) as e:
        raise SnapshotError(f"invalid snapshot {path}: {e}") from None
    try:
        return _parse(doc)
    except ValueError as e:
        raise SnapshotError(f"invalid snapshot {path}: {e}") from None


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _field(obj: dict, key: str, where: str):
    if key not in obj:
        raise ValueError(f"{where}missing field {key}")
    return obj[key]


def _string(obj: dict, key: str, where: str) -> str:
    value = _field(obj, key, where)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}{key} must be a non-empty string")
    return value


def _positive_int(obj: dict, key: str, where: str) -> int:
    value = _field(obj, key, where)
    if not _is_int(value) or value <= 0:
        raise ValueError(f"{where}{key} must be a positive integer")
    return value


def _parse(doc) -> Snapshot:
    if not isinstance(doc, dict):
        raise ValueError("top level must be an object")
    schema = _field(doc, "schema", "")
    if not _is_int(schema) or schema != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    scraped_at = _string(doc, "scraped_at", "")
    target_cents = _positive_int(doc, "target_cents", "")
    raw_skus = _field(doc, "skus", "")
    if not isinstance(raw_skus, list):
        raise ValueError("skus must be a list")
    return Snapshot(
        scraped_at,
        target_cents,
        tuple(_parse_sku(raw, f"skus[{i}]: ") for i, raw in enumerate(raw_skus)),
    )


def _parse_sku(raw, where: str) -> Sku:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}must be an object")
    strings = {key: _string(raw, key, where) for key in _SKU_STRING_FIELDS}
    price_cents = _positive_int(raw, "price_cents", where)
    cap = _field(raw, "cap", where)
    cap_source = _field(raw, "cap_source", where)
    if cap is None:
        if cap_source is not None:
            raise ValueError(f"{where}cap_source must be null when cap is null")
    else:
        if not _is_int(cap) or cap <= 0:
            raise ValueError(f"{where}cap must be a positive integer or null")
        if cap_source not in _CAP_SOURCES:
            raise ValueError(
                f"{where}cap_source must be one of {', '.join(_CAP_SOURCES)} when cap is set"
            )
    return Sku(price_cents=price_cents, cap=cap, cap_source=cap_source, **strings)
