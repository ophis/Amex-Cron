import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
FORBIDDEN = {"scrapling", "playwright", "patchright"}


def _names(requirements):
    return {
        re.split(r"[<>=!~\[;\s(]", r, maxsplit=1)[0].lower().replace("_", "-")
        for r in requirements
        if isinstance(r, str)
    }


def test_runtime_dependencies_are_curl_cffi_without_browser_stacks():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    names = _names(project["dependencies"])
    assert "curl-cffi" in names
    assert not names & FORBIDDEN


def test_no_browser_stack_in_any_dependency_group():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    groups = list(data.get("dependency-groups", {}).values())
    groups += list(data["project"].get("optional-dependencies", {}).values())
    assert not _names(r for group in groups for r in group) & FORBIDDEN
