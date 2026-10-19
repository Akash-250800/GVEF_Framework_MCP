"""Five thesis failure categories; malformed JSON and schema drift are separate subtypes."""
from dataclasses import dataclass, asdict
import copy
import json

FAULTS = (
    "none",
    "malformed_json",       # malformed tool payload
    "type_mismatch",        # wrong parameter type
    "stale_schema",         # outdated or misread tool schema
    "transient_api",        # transport/server HTTP 503
    "transient_timeout",    # transport timeout
    "transient_rate_limit", # HTTP 429
    "wrong_tool",           # valid syntax but semantically wrong tool
)
FAULT_CATEGORIES = ("malformed_payload", "parameter_type_mismatch", "schema_mismatch", "transient_api", "wrong_tool_selection")
CONDITIONS = ("no_verification", "naive_retry", "closed_loop")
FEEDBACKS = ("raw_trace", "schema_diff", "natural_language")

@dataclass
class Fault:
    category: str
    code: str
    message: str
    field: str = ""
    expected: str = ""
    actual: str = ""
    suggested_tool: str = ""
    trace: str = ""
    injected: bool = False
    def dict(self):
        return asdict(self)


def select_field(schema):
    """Pick a required argument, preferring a non-string typed arg."""
    props = schema.get("properties", {})
    required = schema.get("required", list(props))
    for name in required:
        typ = props.get(name, {}).get("type")
        if typ in ("integer", "number", "boolean"):
            return name, typ
    if required:
        name = required[0]
        return name, props.get(name, {}).get("type", "string")
    return None, None


def inject(proposal_text, failure_type, step, catalog):
    """Mutate only the initial candidate. The same mutation applies to every condition."""
    if failure_type in ("none", "transient_api", "transient_timeout", "transient_rate_limit"):
        return proposal_text
    if failure_type == "malformed_json":
        return '{"tool": "unterminated", "args": '
    try:
        call = json.loads(proposal_text)
        if not isinstance(call, dict) or not isinstance(call.get("args"), dict):
            return proposal_text  # preserve naturally faulty model output
    except (ValueError, TypeError):
        return proposal_text
    call = copy.deepcopy(call)
    tool = call.get("tool", "")
    schema = getattr(catalog.get(tool), "input_schema", {})
    field, typ = select_field(schema)
    if failure_type == "type_mismatch":
        if field:
            call["args"][field] = "NOT_A_NUMBER" if typ in ("integer", "number") else (12345 if typ == "string" else "NOT_A_BOOLEAN")
        else:
            call["args"]["unknown_field"] = ["bad"]
    elif failure_type == "stale_schema":
        if field:
            call["args"][field + "_old"] = call["args"].pop(field, None)
        else:
            call["args"]["deprecated_argument"] = "old"
    elif failure_type == "wrong_tool":
        other = next((name for name in sorted(catalog) if name != tool), "__incorrect_tool__")
        call["tool"] = other
    return json.dumps(call, ensure_ascii=False)
