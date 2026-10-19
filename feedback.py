"""RQ4: controlled comparison of three error presentation formats."""
import json
from taxonomy import Fault


def render_feedback(error: Fault, style: str) -> str:
    if style == "raw_trace":
        return error.trace or f"{error.code}: {error.message}"
    if style == "schema_diff":
        # Machine-readable error detail rather than generic advice.
        return json.dumps({"error_code": error.code, "failure_category": error.category,
                           "parameter": error.field, "expected": error.expected,
                           "observed": error.actual, "suggested_tool": error.suggested_tool,
                           "detail": error.message}, ensure_ascii=False, sort_keys=True)
    if style == "natural_language":
        parts = [f"The tool call failed: {error.message}."]
        if error.field:
            parts.append(f"Please correct the argument named '{error.field}'.")
        if error.expected:
            parts.append(f"Expected: {error.expected}.")
        if error.suggested_tool:
            parts.append(f"For this subtask, use '{error.suggested_tool}'.")
        parts.append("Return one corrected JSON tool call, following the MCP tool descriptions.")
        return " ".join(parts)
    raise ValueError(f"Unknown feedback design: {style}")
