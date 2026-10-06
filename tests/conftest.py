import json
from pathlib import Path

import pytest

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
