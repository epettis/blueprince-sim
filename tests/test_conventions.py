"""Checks on the test suite itself, so the conventions in CLAUDE.md hold."""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).parent

#: A docstring shorter than this is almost always a restatement of the test
#: name ("""Test the axis.""") rather than a description of the property.
MIN_DOCSTRING_CHARS = 25


def all_test_functions() -> list[tuple[Path, ast.FunctionDef]]:
    """Every ``test_*`` function defined anywhere under ``tests/``."""
    found = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")):
                found.append((path, node))
    return found


def test_every_test_has_a_docstring():
    """Each test says what it is testing for, so a failure is diagnosable
    without reverse-engineering the assertions (CLAUDE.md convention)."""
    missing = [f"{path.name}::{node.name}"
               for path, node in all_test_functions()
               if not ast.get_docstring(node)]
    assert not missing, (
        "tests missing a docstring describing what they test:\n  "
        + "\n  ".join(missing))


def test_docstrings_describe_rather_than_restate():
    """A one-word docstring restates the function name instead of naming the
    property under test, which is what makes the convention worth having."""
    terse = []
    for path, node in all_test_functions():
        doc = (ast.get_docstring(node) or "").strip()
        if doc and len(doc) < MIN_DOCSTRING_CHARS:
            terse.append(f"{path.name}::{node.name} ({doc!r})")
    assert not terse, (
        "test docstrings too short to describe the property under test:\n  "
        + "\n  ".join(terse))


def test_the_convention_check_sees_this_suite():
    """Guard against the collector silently matching nothing - an empty sweep
    would make both checks above pass vacuously forever."""
    names = {node.name for _, node in all_test_functions()}
    assert len(names) > 100
    assert "test_every_test_has_a_docstring" in names
