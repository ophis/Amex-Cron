import json
import os

import pytest

from lulu_basket.errors import ScrapeError, SnapshotError, SolveError, ToolError
from lulu_basket.snapshot import (
    CAP_LOW_STOCK_COUNT,
    CAP_LOW_STOCK_NO_COUNT,
    Sku,
    Snapshot,
    load_snapshot,
    write_snapshot,
)

SKU_KEYS = [
    "product_id",
    "name",
    "url",
    "color",
    "size",
    "price_cents",
    "cap",
    "cap_source",
]


def raw_sku(**overrides):
    sku = {
        "product_id": "hnsjuvo8dn",
        "name": "Define Jacket *Nulu",
        "url": "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
        "color": "Black",
        "size": "4",
        "price_cents": 6800,
        "cap": None,
        "cap_source": None,
    }
    sku.update(overrides)
    return sku


def raw_doc(**overrides):
    doc = {
        "schema": 1,
        "scraped_at": "2026-10-06T12:00:00Z",
        "target_cents": 7500,
        "skus": [raw_sku()],
    }
    doc.update(overrides)
    return doc


def put(tmp_path, doc):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def invalid_message(path):
    return f"invalid snapshot {path}: "


def test_error_hierarchy():
    for cls in (ScrapeError, SnapshotError, SolveError):
        assert issubclass(cls, ToolError)
    assert issubclass(ToolError, Exception)


def test_cap_source_constants():
    assert CAP_LOW_STOCK_COUNT == "low_stock_count"
    assert CAP_LOW_STOCK_NO_COUNT == "low_stock_no_count"


def test_round_trip(tmp_path):
    snap = Snapshot(
        scraped_at="2026-10-06T12:00:00Z",
        target_cents=7500,
        skus=(
            Sku(
                "hnsjuvo8dn",
                "Define Jacket *Nulu",
                "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
                "Black",
                "4",
                6800,
                None,
                None,
            ),
            Sku(
                "abc123",
                "Align Pant 25\" ™",
                "https://shop.lululemon.com/p/align/abc123",
                "True Navy",
                "6 / 28\"",
                2500,
                2,
                CAP_LOW_STOCK_COUNT,
            ),
            Sku(
                "abc123",
                "Align Pant 25\" ™",
                "https://shop.lululemon.com/p/align/abc123",
                "Black",
                "ONE SIZE",
                2500,
                1,
                CAP_LOW_STOCK_NO_COUNT,
            ),
        ),
    )
    path = tmp_path / "snapshot.json"
    write_snapshot(path, snap)
    loaded = load_snapshot(path)
    assert loaded == snap
    assert isinstance(loaded.skus, tuple)


def test_write_matches_schema_1(tmp_path):
    snap = Snapshot(
        "2026-10-06T12:00:00Z",
        7500,
        (Sku("p1", "N", "https://x/p/n/p1", "Black", "4", 6800, 1, CAP_LOW_STOCK_NO_COUNT),),
    )
    path = tmp_path / "snapshot.json"
    write_snapshot(str(path), snap)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert list(doc) == ["schema", "scraped_at", "target_cents", "skus"]
    assert doc["schema"] == 1
    assert doc["scraped_at"] == "2026-10-06T12:00:00Z"
    assert doc["target_cents"] == 7500
    assert len(doc["skus"]) == 1
    assert list(doc["skus"][0]) == SKU_KEYS
    assert doc["skus"][0]["cap"] == 1
    assert doc["skus"][0]["cap_source"] == "low_stock_no_count"


def test_write_overwrites_existing_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("old", encoding="utf-8")
    write_snapshot(path, Snapshot("2026-10-06T12:00:00Z", 7500, ()))
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]
    assert load_snapshot(path).skus == ()


def test_write_failure_removes_temp_and_keeps_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.json"
    path.write_bytes(b"old")

    def fail_replace(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk on fire"):
        write_snapshot(path, Snapshot("2026-10-06T12:00:00Z", 7500, ()))
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]
    assert path.read_bytes() == b"old"


def test_missing_file(tmp_path):
    path = tmp_path / "nope.json"
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(path)
    assert str(exc.value) == f"snapshot not found: {path}; run scrape first"


def test_unreadable_path_is_invalid_snapshot(tmp_path):
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(tmp_path)
    assert str(exc.value).startswith(invalid_message(tmp_path))


def test_non_json(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


def test_non_utf8(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("doc", [[], "text", 7, None])
def test_top_level_must_be_object(tmp_path, doc):
    path = put(tmp_path, doc)
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("field", ["schema", "scraped_at", "target_cents", "skus"])
def test_missing_top_level_field(tmp_path, field):
    doc = raw_doc()
    del doc[field]
    path = put(tmp_path, doc)
    with pytest.raises(SnapshotError, match=field) as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("schema", [0, 2, "1", 1.0, True, None])
def test_schema_must_be_1(tmp_path, schema):
    path = put(tmp_path, raw_doc(schema=schema))
    with pytest.raises(SnapshotError, match="schema") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("target", [0, -1, True, False, "7500", 75.0, None])
def test_target_cents_must_be_positive_int(tmp_path, target):
    path = put(tmp_path, raw_doc(target_cents=target))
    with pytest.raises(SnapshotError, match="target_cents") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("value", ["", 5, None, ["a"]])
def test_scraped_at_must_be_non_empty_string(tmp_path, value):
    path = put(tmp_path, raw_doc(scraped_at=value))
    with pytest.raises(SnapshotError, match="scraped_at"):
        load_snapshot(path)


@pytest.mark.parametrize("skus", [{}, "x", None, [1], [[]], ["sku"]])
def test_skus_must_be_list_of_objects(tmp_path, skus):
    path = put(tmp_path, raw_doc(skus=skus))
    with pytest.raises(SnapshotError, match="skus") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("field", SKU_KEYS)
def test_missing_sku_field(tmp_path, field):
    sku = raw_sku()
    del sku[field]
    path = put(tmp_path, raw_doc(skus=[sku]))
    with pytest.raises(SnapshotError, match=field):
        load_snapshot(path)


@pytest.mark.parametrize("field", ["product_id", "name", "url", "color", "size"])
@pytest.mark.parametrize("value", ["", 5, None, True, ["a"]])
def test_sku_string_fields_must_be_non_empty_strings(tmp_path, field, value):
    path = put(tmp_path, raw_doc(skus=[raw_sku(**{field: value})]))
    with pytest.raises(SnapshotError, match=field) as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("price", [0, -100, True, 68.0, "6800", None])
def test_price_cents_must_be_positive_int(tmp_path, price):
    path = put(tmp_path, raw_doc(skus=[raw_sku(price_cents=price)]))
    with pytest.raises(SnapshotError, match="price_cents") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("cap", [0, -1, True, 1.0, "2"])
def test_cap_must_be_positive_int_or_null(tmp_path, cap):
    sku = raw_sku(cap=cap, cap_source=CAP_LOW_STOCK_COUNT)
    path = put(tmp_path, raw_doc(skus=[sku]))
    with pytest.raises(SnapshotError, match="cap") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("source", [None, "bogus", "", 3])
def test_cap_set_requires_known_cap_source(tmp_path, source):
    path = put(tmp_path, raw_doc(skus=[raw_sku(cap=2, cap_source=source)]))
    with pytest.raises(SnapshotError, match="cap_source") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


@pytest.mark.parametrize("source", [CAP_LOW_STOCK_COUNT, CAP_LOW_STOCK_NO_COUNT, "bogus"])
def test_cap_null_requires_null_cap_source(tmp_path, source):
    path = put(tmp_path, raw_doc(skus=[raw_sku(cap=None, cap_source=source)]))
    with pytest.raises(SnapshotError, match="cap_source") as exc:
        load_snapshot(path)
    assert str(exc.value).startswith(invalid_message(path))


def test_error_names_the_offending_sku(tmp_path):
    good, bad = raw_sku(), raw_sku(price_cents=0)
    path = put(tmp_path, raw_doc(skus=[good, bad]))
    with pytest.raises(SnapshotError, match=r"skus\[1\]"):
        load_snapshot(path)


def test_valid_hand_written_snapshot_loads(tmp_path):
    path = put(tmp_path, raw_doc(skus=[raw_sku(cap=1, cap_source=CAP_LOW_STOCK_NO_COUNT)]))
    snap = load_snapshot(path)
    assert snap == Snapshot(
        "2026-10-06T12:00:00Z",
        7500,
        (
            Sku(
                "hnsjuvo8dn",
                "Define Jacket *Nulu",
                "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn",
                "Black",
                "4",
                6800,
                1,
                CAP_LOW_STOCK_NO_COUNT,
            ),
        ),
    )
