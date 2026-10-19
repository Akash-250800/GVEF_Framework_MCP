import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from taxonomy import FAULTS, FAULT_CATEGORIES, FEEDBACKS, inject, Fault
from benchmarks import inventory_tasks, load_bfcl
from verification import parse_proposal, validate
from feedback import render_feedback


def _tools():
    return {
        "reserve_stock": SimpleNamespace(input_schema={"type":"object", "properties":{"sku":{"type":"string"},"quantity":{"type":"integer"}},"required":["sku","quantity"],"additionalProperties":False}),
        "check_stock": SimpleNamespace(input_schema={"type":"object", "properties":{"sku":{"type":"string"}}, "required":["sku"],"additionalProperties":False}),
    }


def test_all_tasks_are_multi_tool_and_distinct():
    tasks=inventory_tasks()
    assert len(tasks)==20
    assert len(set(task["id"] for task in tasks))==20
    assert all(len(task["steps"])>=3 for task in tasks)


def test_five_proposal_failures():
    tools=_tools()
    step=inventory_tasks()[0]["steps"][1]
    text=json.dumps({"tool":"reserve_stock","args":step["expected_args"]})
    assert len(FAULT_CATEGORIES)==5
    for name in FAULTS:
        mutated=inject(text,name,step,tools)
        if name in ("none","transient_api","transient_timeout","transient_rate_limit"):
            assert mutated==text
        elif name=="malformed_json":
            assert parse_proposal(mutated)[1].code=="invalid_json"
        else:
            parsed,err=parse_proposal(mutated)
            assert err is None
            assert validate(parsed,tools,step) is not None


def test_every_feedback_format():
    error=Fault("schema_mismatch","jsonschema_required","'quantity' is a required property",field="quantity",expected="integer",actual="missing",suggested_tool="reserve_stock",trace="ValidationError: quantity missing")
    assert len(FEEDBACKS)==3
    for format in FEEDBACKS:
        value=render_feedback(error,format)
        assert isinstance(value,str) and value
    assert "quantity" in render_feedback(error,"schema_diff")
    assert "quantity" in render_feedback(error,"natural_language")
    assert "ValidationError" in render_feedback(error,"raw_trace")


def test_preflight_guards_wrong_tool_and_safety():
    tools=_tools()
    step=inventory_tasks()[0]["steps"][1]
    wrong_tool={"tool":"check_stock", "args":{"sku":"PEN"}}
    assert validate(wrong_tool,tools,step).code=="semantic_tool_selection"
    unsafe={"tool":"reserve_stock","args":{"sku":"PEN","quantity":-1}}
    assert validate(unsafe,tools,step) is not None
    valid={"tool":"reserve_stock","args":{"sku":"PEN","quantity":3}}
    assert validate(valid,tools,step) is None


def test_bfcl_single_call_adapter_fixture(tmp_path):
    q=tmp_path/"BFCL_questions.jsonl"
    a=tmp_path/"BFCL_answers.jsonl"
    q.write_text(json.dumps({"id":"simple_python_1","question":[{"role":"user","content":"Double three."}],"function":[{"name":"double","description":"Double a value","parameters":{"type":"object","properties":{"x":{"type":"integer"}},"required":["x"]}}]})+"\n",encoding="utf-8")
    a.write_text(json.dumps({"id":"simple_python_1","ground_truth":[{"double":{"x":[3]}}]})+"\n",encoding="utf-8")
    tasks,skipped=load_bfcl(q,a)
    assert not skipped
    assert len(tasks)==1
    assert tasks[0]["accepted_calls"]==[{"tool":"double","args":{"x":3}}]
    assert tasks[0]["description"]=="Double three."


def test_bfcl_v3_official_dict_and_float_schema_conversion(tmp_path):
    from benchmarks import load_bfcl
    question = {"id": "simple_0", "question": [[{"role": "user", "content": "Calculate area for base 10 and height 5"}]],
                "function": [{"name": "calculate_triangle_area", "description": "Area",
                              "parameters": {"type": "dict", "properties": {
                                  "base": {"type": "integer"}, "height": {"type": "integer"}, "ratio": {"type": "float"}},
                                  "required": ["base", "height"]}}]}
    answer = {"id": "simple_0", "ground_truth": [{"calculate_triangle_area": {"base": [10], "height": [5]}}]}
    q = tmp_path / "questions.jsonl"
    a = tmp_path / "answers.jsonl"
    q.write_text(json.dumps(question) + "\n", encoding="utf-8")
    a.write_text(json.dumps(answer) + "\n", encoding="utf-8")
    tasks, rejected = load_bfcl(q, a, 1)
    assert not rejected
    assert len(tasks) == 1
    schema = tasks[0]["bfcl_tools"][0]["input_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["ratio"]["type"] == "number"
