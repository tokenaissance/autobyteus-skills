from __future__ import annotations

import pytest

from browser_automation.script import normalize_script


@pytest.mark.parametrize(
    "script",
    [
        "async (arg) => arg.x",
        "async arg => arg.x",
        "async () => 42",
        "async(arg) => { return arg.x }",
        "  async value => value",
        "async function (arg) { return arg.x }",
        "(arg) => arg.x",
        "arg => arg.x",
        "() => 1",
    ],
)
def test_complete_functions_are_passed_through_unchanged(script: str) -> None:
    assert normalize_script(script) == script.strip()


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("document.title", "(arg) => (document.title)"),
        ("return document.title", "(arg) => { return document.title }"),
        ("asyncValue + 1", "(arg) => (asyncValue + 1)"),
    ],
)
def test_expressions_and_bodies_are_wrapped(script: str, expected: str) -> None:
    assert normalize_script(script) == expected
