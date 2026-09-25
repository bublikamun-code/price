"""Export the checked-in API v2 OpenAPI surface.

The application exposes v1 and v2 side by side.  A full-document snapshot would
therefore change whenever an unrelated v1 route changes, so this exporter keeps
only v2 paths and the component definitions reachable from them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.main import app


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "openapi"
    / "api-v2.openapi.json"
)


def _walk_refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        refs: list[str] = []
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            refs.append(ref)
        for child in value.values():
            refs.extend(_walk_refs(child))
        return refs
    if isinstance(value, list):
        refs = []
        for child in value:
            refs.extend(_walk_refs(child))
        return refs
    return []


def _resolve_ref(document: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"Only local OpenAPI refs are supported: {ref}")
    value: Any = document
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def v2_openapi_document(document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a stable, v2-only OpenAPI document from the application spec."""
    document = document or app.openapi()
    paths = {
        path: definition
        for path, definition in document["paths"].items()
        if path.startswith("/api/v2")
    }
    if not paths:
        raise ValueError("The application has no API v2 paths")

    pending = _walk_refs(paths)
    used_refs: set[str] = set()
    while pending:
        ref = pending.pop()
        if ref in used_refs:
            continue
        used_refs.add(ref)
        pending.extend(_walk_refs(_resolve_ref(document, ref)))

    components: dict[str, Any] = {}
    for ref in sorted(used_refs):
        prefix = "#/components/"
        if not ref.startswith(prefix):
            continue
        category, name = ref[len(prefix) :].split("/", 1)
        components.setdefault(category, {})[name] = _resolve_ref(document, ref)

    return {
        "openapi": document["openapi"],
        "info": document["info"],
        "paths": paths,
        "components": components,
    }


def export_v2_contract(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(v2_openapi_document(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    print(export_v2_contract(args.output))


if __name__ == "__main__":
    main()
