"""Tier 1: deterministic schema validation (JSON Schema, draft 2020-12)."""

from __future__ import annotations

import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from agentescrow.domain.models import SchemaResult

logger = logging.getLogger(__name__)
_MAX_REPORTED_ERRORS = 10


class ContractSchemaError(ValueError):
    """The *contract's* schema is itself invalid. That is the buyer's mistake, not the worker's."""


def validate_deliverable(deliverable: Any, schema: dict[str, Any]) -> SchemaResult:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ContractSchemaError(f"Contract schema is invalid: {exc.message}") from exc

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(deliverable), key=lambda e: list(e.absolute_path))
    messages = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors[:_MAX_REPORTED_ERRORS]
    ]
    valid = not errors
    logger.info("Tier 1 schema check: %s (%d error(s))", "PASS" if valid else "FAIL", len(errors))
    return SchemaResult(valid=valid, errors=messages, score=1.0 if valid else 0.0)
