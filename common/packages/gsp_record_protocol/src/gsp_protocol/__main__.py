"""Validate a saved snapshot without starting an application or accessing Git."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import ProtocolError, validate_snapshot


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-snapshot")
    validate.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.path.open("r", encoding="utf-8") as stream:
            snapshot = json.load(stream, object_pairs_hook=_pairs,
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))
        report = validate_snapshot(snapshot)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, RecursionError, ProtocolError) as error:
        result = {"valid": False, "code": getattr(error, "code", "input"), "message": str(error)}
        if getattr(error, "fields", None):
            result["fields"] = error.fields
        print(json.dumps(result, ensure_ascii=True, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
