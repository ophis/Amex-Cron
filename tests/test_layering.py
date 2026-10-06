import ast
from pathlib import Path

import pytest

SOLVE_DIR = Path(__file__).resolve().parent.parent / "src" / "lulu_basket" / "solve"
SOLVE_PACKAGE = "lulu_basket.solve"
FORBIDDEN = ("lulu_basket.scrape", "curl_cffi")


def imported_names(source: str, package: str = SOLVE_PACKAGE) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            anchor = package.split(".")
            parts = anchor[: len(anchor) - node.level + 1] if node.level else []
            if node.module:
                parts.append(node.module)
            base = ".".join(parts)
            names.append(base)
            names += [f"{base}.{alias.name}" for alias in node.names]
    return names


def forbidden_imports(source: str) -> list[str]:
    return [
        name
        for name in imported_names(source)
        if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
    ]


def test_solve_modules_do_not_import_the_scrape_layer_or_curl_cffi():
    files = sorted(SOLVE_DIR.glob("*.py"))
    assert {f.name for f in files} >= {"items.py", "knapsack.py", "report.py"}
    for file in files:
        assert forbidden_imports(file.read_text(encoding="utf-8")) == [], file.name


@pytest.mark.parametrize(
    "source",
    [
        "import curl_cffi",
        "import curl_cffi.requests as r",
        "from curl_cffi import requests",
        "import lulu_basket.scrape.parse",
        "from lulu_basket.scrape import fetch",
        "from lulu_basket import scrape",
        "from ..scrape import parse",
        "from .. import scrape",
        "def f():\n    from lulu_basket.scrape.fetch import Fetcher",
    ],
)
def test_scan_detects_forbidden_imports(source):
    assert forbidden_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from lulu_basket.snapshot import Sku",
        "from lulu_basket.errors import SolveError",
        "from .items import Item",
        "from . import items",
        "from lulu_basket import snapshot",
    ],
)
def test_scan_allows_shared_and_sibling_imports(source):
    assert forbidden_imports(source) == []
