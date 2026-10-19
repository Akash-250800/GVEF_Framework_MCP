"""Built-in multi-tool sandbox and official BFCL JSONL adapter (where compatible)."""
import json
import itertools
from pathlib import Path
from inventory_data import INITIAL_STOCK, RESERVE_AMOUNTS


def inventory_tasks():
    result = []
    for sku, qty in RESERVE_AMOUNTS.items():
        before = INITIAL_STOCK[sku]
        result.append({
            "id": f"inventory_{sku.lower()}", "source": "synthetic_inventory",
            "description": f"Check the stock for {sku}, reserve exactly {qty} units, and then confirm the new stock level.",
            "fault_step": 1,
            "steps": [
                {"instruction": f"Check current stock of {sku}.", "expected_tool":"check_stock", "expected_args":{"sku":sku},
                 "expected_output":{"sku":sku,"available":before},"mutating":False},
                {"instruction": f"Reserve exactly {qty} units of SKU {sku}.","expected_tool":"reserve_stock","expected_args":{"sku":sku,"quantity":qty},
                 "expected_output":{"sku":sku,"reserved":qty,"remaining":before-qty},"mutating":True},
                {"instruction": f"Check remaining stock for {sku} after reservation.","expected_tool":"check_stock","expected_args":{"sku":sku},
                 "expected_output":{"sku":sku,"available":before-qty},"mutating":False},
            ],
        })
    return result


def _extract_user_text(question):
    if isinstance(question, str):
        return question
    fragments = []
    def recurse(obj):
        if isinstance(obj, str):
            fragments.append(obj)
        elif isinstance(obj, dict):
            if obj.get("role") == "user" and isinstance(obj.get("content"), str):
                fragments.append(obj["content"])
            elif "content" in obj:
                recurse(obj["content"])
            elif "question" in obj:
                recurse(obj["question"])
        elif isinstance(obj, list):
            for element in obj:
                recurse(element)
    recurse(question)
    return "\n".join(fragments)


def _gold_variants(record):
    """Supported BFCL single-call: {function_name: {arg:[possible_values]}}."""
    entries = record.get("ground_truth") or record.get("answer") or []
    if isinstance(entries, dict):
        entries = [entries]
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for name, params in entry.items():
            if not isinstance(params, dict):
                continue
            keys = list(params)
            values = [v if isinstance(v, list) else [v] for v in params.values()]
            for combination in itertools.product(*values):
                parsed.append({"tool": name, "args": dict(zip(keys,combination))})
                if len(parsed) > 128:
                    raise ValueError("More than 128 valid gold combinations; exclude this case")
    return parsed


def _normalize_bfcl_schema(schema):
    """BFCL uses `type: dict`, and sometimes `float`; JSON Schema uses object/number."""
    if isinstance(schema, list):
        return [_normalize_bfcl_schema(x) for x in schema]
    if isinstance(schema, dict):
        output = {k: _normalize_bfcl_schema(v) for k,v in schema.items()}
        if output.get("type") == "dict":
            output["type"] = "object"
        elif output.get("type") == "float":
            output["type"] = "number"
        elif output.get("type") == "tuple":
            output["type"] = "array"
        return output
    return schema


def load_bfcl(question_path, answer_path, limit=None):
    """Adapt **single-call JSONL** question/function + possible_answer files from BFCL.

    Unsupported parallel/multi-turn/AST-expression cases are rejected rather than
    silently guessed. This does not claim to reproduce official BFCL scoring.
    """
    if not question_path or not answer_path:
        raise ValueError("--bfcl-questions and --bfcl-answers are required for BFCL tasks")
    with Path(answer_path).open(encoding="utf-8") as fh:
        gold = {str(x["id"]): x for line in fh if (x := json.loads(line.strip()))}
    tasks, rejected = [], []
    with Path(question_path).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            identifier = str(record.get("id", ""))
            tools = record.get("function")
            # Guard against falsely treating BFCL multi-turn or parallel cases as single-call.
            if "multi_turn" in identifier or "parallel" in identifier:
                rejected.append({"id":identifier,"reason":"parallel/multi-turn cases need their official evaluator"})
                continue
            question_data=record.get("question", "")
            user_turns=[]
            def collect_user_turns(item):
                if isinstance(item,dict):
                    if item.get("role")=="user":
                        user_turns.append(item)
                    for value in item.values():
                        if isinstance(value,(list,dict)):
                            collect_user_turns(value)
                elif isinstance(item,list):
                    for value in item:
                        collect_user_turns(value)
            collect_user_turns(question_data)
            if len(user_turns)>1:
                rejected.append({"id":identifier,"reason":"multiple user turns unsupported by single-call adapter"})
                continue
            choices = _gold_variants(gold.get(identifier, {}))
            prompt = _extract_user_text(record.get("question", ""))
            if not prompt or not isinstance(tools, list) or not tools or not choices:
                rejected.append({"id":identifier,"reason":"unsupported question/functions/ground_truth"})
                continue
            normalized = []
            for t in tools:
                try:
                    name = t["name"]
                    schema = t.get("parameters", {"type":"object","properties":{}})
                    if isinstance(schema, str):
                        schema = json.loads(schema)
                    if isinstance(schema.get("properties"), str):
                        schema["properties"] = json.loads(schema["properties"])
                    schema = _normalize_bfcl_schema(schema)
                    if schema.get("type") != "object":
                        raise ValueError("non-object schema")
                    normalized.append({"name":name, "description":t.get("description", ""),"input_schema":schema})
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    normalized=[]
                    break
            if not normalized:
                rejected.append({"id":identifier,"reason":"unsupported tool schema"})
                continue
            tasks.append({"id":identifier,"source":"bfcl_single_call", "description":prompt,"bfcl_tools":normalized,
                          "fault_step":0, "accepted_calls":choices,
                          "steps":[{"instruction":prompt,"expected_tool":"", "expected_args":{},
                                    "mutating":False,"bfcl_gold":choices}]})
            if limit and len(tasks) >= limit:
                break
    if not tasks:
        raise RuntimeError(f"No compatible BFCL tasks could be adapted; rejected {len(rejected)} entries. Try a BFCL simple/multiple single-call JSONL subset.")
    return tasks, rejected


def make_bfcl_server(task):
    """Low-level MCP server preserves each benchmark tool's original JSON Schema."""
    from mcp.server import Server
    from mcp.types import Tool, ListToolsResult, CallToolResult, TextContent
    from jsonschema import Draft202012Validator
    tools = [Tool(name=x["name"],description=x["description"],input_schema=x["input_schema"]) for x in task["bfcl_tools"]]
    catalog = {t.name: t for t in tools}
    async def on_list_tools(ctx, params):
        return ListToolsResult(tools=tools)
    async def on_call_tool(ctx, params):
        if params.name not in catalog:
            return CallToolResult(content=[TextContent(type="text",text="Unknown tool")],is_error=True)
        args = params.arguments or {}
        errors = list(Draft202012Validator(catalog[params.name].input_schema).iter_errors(args))
        if errors:
            return CallToolResult(content=[TextContent(type="text",text=f"Schema: {errors[0].message}")],is_error=True)
        # No external BFCL side effects are executed: a sandbox call and AST/oracle check.
        data={"tool":params.name,"args":args}
        return CallToolResult(content=[TextContent(type="text",text=json.dumps(data))],structured_content=data)
    return Server("BFCL MCP schema adapter", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
