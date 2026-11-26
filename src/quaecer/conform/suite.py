# SPDX-License-Identifier: Apache-2.0
"""Run bounded JSON conformance cases through explicit local commands."""

import json
import math
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NoReturn

MAX_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_FIELDS = {"id", "requirements", "description", "comparison"}


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate JSON member")
    return obj


def _constant(text: str) -> NoReturn:
    raise ValueError(f"invalid JSON literal: {text}")


def _parse_int(text: str) -> int:
    value = int(text)
    if abs(value) > 2**53 - 1:
        raise ValueError("integer is outside the interoperable JSON range")
    return value


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _json(raw: bytes) -> Any:
    if len(raw) > MAX_BYTES:
        raise ValueError("JSON size limit exceeded")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique,
        parse_constant=_constant,
        parse_int=_parse_int,
        parse_float=_parse_float,
    )


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("case inputs must be regular files")
    with path.open("rb") as stream:
        return _json(stream.read(MAX_BYTES + 1))


type ValueKey = tuple[Any, ...]


def _same(value: Any, path: tuple[str, ...], unordered: tuple[str, ...] | None) -> ValueKey:
    if isinstance(value, dict):
        return (
            "object",
            tuple(
                sorted((key, _same(item, (*path, key), unordered)) for key, item in value.items())
            ),
        )
    if isinstance(value, list):
        items = tuple(_same(item, (*path, str(i)), unordered) for i, item in enumerate(value))
        return ("set", frozenset(items)) if path == unordered else ("array", items)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", value)
    return ("literal", value)


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _subset(item, actual[key]) for key, item in expected.items()
        )
    return _same(expected, (), None) == _same(actual, (), None)


def _pointer(pointer: str) -> tuple[str, ...]:
    if not pointer:
        return ()
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("invalid JSON pointer")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def _array_at(value: Any, path: tuple[str, ...]) -> bool:
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            if len(part) > len(str(len(value))) or int(part) >= len(value):
                return False
            value = value[int(part)]
        else:
            return False
    return isinstance(value, list)


def matches(expected: Any, actual: Any, comparison: str) -> bool:
    """Compare JSON values without treating booleans as numbers.

    >>> matches({"score": 1}, {"score": True}, "canonical-equal")
    False
    >>> matches({"items": ["a", "b"]}, {"items": ["b", "a"]}, "set-equal-on:/items")
    True
    """
    if comparison == "subset":
        return _subset(expected, actual)
    if comparison == "canonical-equal":
        return _same(expected, (), None) == _same(actual, (), None)
    if comparison.startswith("set-equal-on:"):
        path = _pointer(comparison.removeprefix("set-equal-on:"))
        if not _array_at(expected, path) or not _array_at(actual, path):
            return False
        return _same(expected, (), path) == _same(actual, (), path)
    raise ValueError("unknown comparison mode")


@dataclass(frozen=True)
class Case:
    """One checked request, expected response and comparison rule."""

    id: str
    request: Any
    expected: Any
    comparison: str


@dataclass(frozen=True)
class Result:
    """The observed outcome for one case."""

    id: str
    outcome: str
    reason: str


def load_suite(root: Path) -> tuple[Case, ...]:
    """Read and validate all cases before starting an implementation."""
    cases = []
    for directory in sorted(root.iterdir()):
        if directory.is_symlink():
            raise ValueError("symlinked suite entry")
        if not directory.is_dir():
            continue
        metadata = _load(directory / "case.json")
        if (
            not isinstance(metadata, dict)
            or metadata.keys() != _FIELDS
            or not _ID.fullmatch(directory.name)
            or metadata["id"] != directory.name
            or not isinstance(metadata["description"], str)
            or not metadata["description"].strip()
        ):
            raise ValueError(f"invalid metadata for {directory.name}")
        links = metadata["requirements"]
        if (
            not isinstance(links, list)
            or not links
            or not all(isinstance(link, str) and _ID.fullmatch(link) for link in links)
            or len(set(links)) != len(links)
        ):
            raise ValueError(f"invalid requirement links for {directory.name}")
        request = _load(directory / "input.json")
        expected = _load(directory / "expected.json")
        comparison = metadata["comparison"]
        if not isinstance(comparison, str) or not matches(expected, expected, comparison):
            raise ValueError(f"invalid comparison for {directory.name}")
        cases.append(Case(directory.name, request, expected, comparison))
    if not cases:
        raise ValueError("suite is empty")
    return tuple(cases)


def run_case(case: Case, command: list[str], timeout: float) -> Result:
    """Run a trusted command once and classify its response."""
    request = json.dumps(case.request, ensure_ascii=True).encode("utf-8") + b"\n"
    with tempfile.TemporaryFile() as output:
        try:
            completed = subprocess.run(
                command,
                input=request,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Result(case.id, "cantTell", "timeout")
        except OSError:
            return Result(case.id, "cantTell", "startup_error")
        if completed.returncode:
            return Result(case.id, "cantTell", "exit_error")
        output.seek(0)
        try:
            response = _json(output.read(MAX_BYTES + 1))
            equal = matches(case.expected, response, case.comparison)
        except (ValueError, RecursionError):
            return Result(case.id, "cantTell", "invalid_response")
    return Result(case.id, "passed", "matched") if equal else Result(case.id, "failed", "different")


def report(results: tuple[Result, ...]) -> str:
    """Render one EARL assertion per case with fixed, safe term spellings."""
    lines = ["@prefix earl: <http://www.w3.org/ns/earl#> .", ""]
    for result in results:
        if not _ID.fullmatch(result.id) or result.outcome not in {"passed", "failed", "cantTell"}:
            raise ValueError("invalid result")
        lines.extend(
            (
                "[] a earl:Assertion ;",
                "   earl:assertedBy <urn:conform:runner> ;",
                "   earl:subject <urn:conform:implementation> ;",
                f"   earl:test <urn:conform:case:{result.id}> ;",
                "   earl:mode earl:automatic ;",
                f"   earl:result [ a earl:TestResult ; earl:outcome earl:{result.outcome} ] .",
                "",
            )
        )
    return "\n".join(lines)


def summary(results: tuple[Result, ...]) -> str:
    """Return a deterministic JSON summary including per-case operational errors."""
    return json.dumps(
        {
            "counts": {
                status: sum(result.outcome == status for result in results)
                for status in ("passed", "failed", "cantTell")
            },
            "cases": [asdict(result) for result in results],
        },
        sort_keys=True,
    )
