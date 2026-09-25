"""Small dependency-free compatibility check for the checked-in API v2 contract.

The snapshot exporter proves that the artifact is reproducible. This check adds
consumer-facing guardrails for changes that are reproducible but breaking.
It intentionally checks a conservative subset of OpenAPI compatibility rules:
removed paths/methods, newly required request parameters, narrowed enums, and
removed success responses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        raise ValueError(f"OpenAPI document must be an object: {path}")
    return document


def _operations(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        return operations
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                operations[(path, method.lower())] = operation
    return operations


def _parameters(operation: dict[str, Any], path_item: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        if isinstance(source, list):
            values.extend(item for item in source if isinstance(item, dict))
    return values


def _enums(parameter: dict[str, Any]) -> set[Any] | None:
    schema = parameter.get("schema")
    if not isinstance(schema, dict):
        return None
    values = schema.get("enum")
    return set(values) if isinstance(values, list) else None


def _key(parameter: dict[str, Any]) -> tuple[str, str]:
    return (str(parameter.get("in", "")), str(parameter.get("name", "")))


def _success_statuses(operation: dict[str, Any]) -> set[str]:
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        return set()
    return {str(status) for status in responses if str(status).startswith("2")}


def check_breaking_changes(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    baseline_ops = _operations(baseline)
    current_ops = _operations(current)
    problems: list[str] = []

    for key, old_operation in baseline_ops.items():
        path, method = key
        new_operation = current_ops.get(key)
        if new_operation is None:
            problems.append(f"removed {method.upper()} {path}")
            continue

        old_path_item = baseline.get("paths", {}).get(path, {})
        new_path_item = current.get("paths", {}).get(path, {})
        old_parameters = {
            _key(parameter): parameter
            for parameter in _parameters(old_operation, old_path_item)
        }
        new_parameters = {
            _key(parameter): parameter
            for parameter in _parameters(new_operation, new_path_item)
        }
        for key, old_parameter in old_parameters.items():
            new_parameter = new_parameters.get(key)
            if new_parameter is None:
                continue
            if new_parameter.get("required") and not old_parameter.get("required"):
                problems.append(f"new required parameter {key[0]}:{key[1]} on {method.upper()} {path}")
            old_enum = _enums(old_parameter)
            new_enum = _enums(new_parameter)
            if old_enum and new_enum and not old_enum.issubset(new_enum):
                removed_values = sorted(str(value) for value in old_enum - new_enum)
                problems.append(
                    f"narrowed enum for {key[0]}:{key[1]} on {method.upper()} {path}: "
                    + ", ".join(removed_values)
                )

        removed_statuses = _success_statuses(old_operation) - _success_statuses(new_operation)
        for status in sorted(removed_statuses):
            problems.append(f"removed {status} response on {method.upper()} {path}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="previous v2 OpenAPI JSON")
    parser.add_argument("current", type=Path, help="current v2 OpenAPI JSON")
    args = parser.parse_args()
    problems = check_breaking_changes(_load(args.baseline), _load(args.current))
    if problems:
        for problem in problems:
            print(f"breaking: {problem}", file=sys.stderr)
        return 1
    print("API v2 semantic compatibility check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
