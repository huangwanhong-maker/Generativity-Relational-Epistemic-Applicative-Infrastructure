"""One explicit JSON Schema vocabulary, also distributed as a JSON resource."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator, FormatChecker


def schema(kind: str) -> dict:
    document = json.loads(files("gsp_protocol").joinpath("schemas/protocol.schema.json").read_text(encoding="utf-8"))
    document.pop("anyOf", None)
    document["$ref"] = f"#/$defs/{kind}"
    return document


@lru_cache(maxsize=16)
def validator(kind: str) -> Draft202012Validator:
    return Draft202012Validator(schema(kind), format_checker=FormatChecker())
