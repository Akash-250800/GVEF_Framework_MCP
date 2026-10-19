"""Tests use a mocked LOCAL Ollama HTTP endpoint: no model/download needed."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents import OllamaAgent, new_agent
from check_ollama import check


def catalog():
    return {"reserve_stock": SimpleNamespace(
        name="reserve_stock", description="Reserve units", input_schema={
            "type":"object", "properties":{"sku":{"type":"string"},"quantity":{"type":"integer"}},
            "required":["sku", "quantity"]})}


def response(msg, inp=42, out=17):
    return httpx.Response(200, json={"message": msg, "prompt_eval_count": inp, "eval_count": out})


@pytest.mark.asyncio
async def test_ollama_native_tool_call_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    requests=[]
    async def handler(request):
        requests.append(json.loads(request.content))
        return response({"tool_calls": [{"function": {"name":"reserve_stock", "arguments":{"sku":"PEN","quantity":3}}}]})
    a=OllamaAgent()
    await a.client.aclose()
    a.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result, tokens=await a.generate({"description":"Reserve 3 pens"},{"instruction":"Reserve 3 pens"},catalog())
    assert json.loads(result)=={"tool":"reserve_stock","args":{"sku":"PEN","quantity":3}}
    assert tokens=={"input":42,"output":17}
    assert requests[0]["model"]=="qwen2.5:1.5b"
    assert requests[0]["tools"][0]["function"]["name"]=="reserve_stock"
    assert requests[0]["stream"] is False
    assert "OPENAI_API_KEY" not in requests[0]
    await a.aclose()


@pytest.mark.asyncio
async def test_ollama_fallback_json_and_feedback():
    prompts=[]
    async def handler(request):
        data=json.loads(request.content)
        prompts.append(data["messages"][-1]["content"])
        return response({"content": '{"tool":"reserve_stock","args":{"sku":"PEN","quantity":3}}'})
    a=OllamaAgent()
    await a.client.aclose()
    a.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result,usage=await a.generate({"description":"Reserve"},{"instruction":"Reserve PEN"},catalog(),feedback="Expected integer")
    assert json.loads(result)["args"]["quantity"]==3
    assert "Expected integer" in prompts[0]
    assert usage["input"]==42
    await a.aclose()


@pytest.mark.asyncio
async def test_ollama_errors_on_multiple_calls():
    async def handler(request):
        return response({"tool_calls": [{"function":{"name":"a","arguments":{}}}, {"function":{"name":"b","arguments":{}}}]})
    a=OllamaAgent()
    await a.client.aclose()
    a.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result,_=await a.generate({"description":"x"},{"instruction":"x"},catalog())
    assert json.loads(result)["error"]=="multiple_tool_calls"
    await a.aclose()


def test_check_ollama_tags_and_generation():
    def handler(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200,json={"models":[{"name":"qwen2.5:1.5b"}]})
        return httpx.Response(200,json={"message":{"content":"READY"},"prompt_eval_count":6,"eval_count":1})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check(client=client)


def test_new_agent_ollama_and_llm_alias():
    assert isinstance(new_agent('ollama','qwen2.5:1.5b'),OllamaAgent)
    assert isinstance(new_agent('llm','qwen2.5:1.5b'),OllamaAgent)
