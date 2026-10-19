"""Schema + semantic intent + safety invariants; never execute during verification."""
from jsonschema import Draft202012Validator
from taxonomy import Fault
import json
import traceback


def _trace_for_validation(error):
    """Generate an actual Python traceback for the raw-stack-trace feedback arm."""
    try:
        raise error
    except Exception:
        return traceback.format_exc()


def parse_proposal(raw):
    if not isinstance(raw, str):
        return None, Fault("malformed_payload", "not_text", "LLM proposal was not a string", actual=type(raw).__name__)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, Fault("malformed_payload", "invalid_json", str(exc), expected='JSON {"tool":string,"args":object}',actual=raw[:180], trace="".join(traceback.format_exception(exc)))
    if not isinstance(value, dict) or not isinstance(value.get("tool"), str) or not isinstance(value.get("args"), dict):
        return None, Fault("malformed_payload", "bad_shape", "tool must be a string and args an object", expected='{"tool":string,"args":object}',actual=repr(value)[:180])
    return {"tool": value["tool"], "args": value["args"]}, None


def validate(call, catalog, step, *, schema_enabled=True, safety_enabled=True):
    if call["tool"] not in catalog:
        return Fault("incorrect_tool", "unknown_tool", f"Tool {call['tool']!r} does not exist",expected=f"one of {sorted(catalog)}", actual=call["tool"],suggested_tool=step.get("expected_tool", ""))
    if schema_enabled:
        schema = catalog[call["tool"]].input_schema
        errors = sorted(Draft202012Validator(schema).iter_errors(call["args"]), key=lambda e: (list(map(str,e.path)),e.message))
        if errors:
            err = errors[0]
            field = ".".join(str(x) for x in err.path)
            if err.validator == "required":
                try:
                    field = str(err.message).split("'")[1]
                except IndexError:
                    field = "required field"
            expected = repr(err.validator_value)
            category = "parameter_type_mismatch" if err.validator == "type" else "schema_mismatch"
            return Fault(category, f"jsonschema_{err.validator}",err.message,field=field,expected=expected,actual=repr(call["args"]),trace=_trace_for_validation(err))
    if safety_enabled:
        # An intent check is independent of schema validity. Prevent valid, wrong-tool actions.
        wanted = step.get("expected_tool", "")
        if wanted and call["tool"] != wanted:
            return Fault("incorrect_tool", "semantic_tool_selection",f"Selected {call['tool']}, but the current task requires {wanted}", expected=wanted,actual=call["tool"],suggested_tool=wanted)
        if call["tool"] == "reserve_stock":
            qty = call["args"].get("quantity", None)
            if type(qty) is not int or qty <= 0 or qty > 100:
                return Fault("safety_violation", "unsafe_quantity", "Reservations must use a positive integer quantity no more than 100", field="quantity",expected="integer 1..100",actual=repr(qty))
        # Do not compare with task ground-truth arguments: that would leak the
        # answer into verification and unfairly inflate the closed-loop score.
    return None


def unwrap_mcp_reply(result):
    if getattr(result, "is_error", False):
        message = " | ".join(getattr(item,"text",str(item)) for item in (result.content or []))
        return None, Fault("execution_failure", "mcp_tool_error",message or "MCP tool returned an error",trace=message)
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if data is None:
        text = " ".join(str(getattr(item,"text",item)) for item in (getattr(result,"content",[]) or []))
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = {"text": text}
    return data, None
