"""Mock-only integration check of experiment logic when no MCP SDK is installed.
This NEVER substitutes for SDK integration and live-model testing.
"""
import asyncio
import importlib
import importlib.util
import inspect
import json
import jsonschema
import sys
import types
import pytest


def test_mock_mcp_round_trip_policy_matrix(monkeypatch,tmp_path):
    if importlib.util.find_spec("mcp") is not None:
        pytest.skip("Real MCP SDK is installed; run tests/test_policies.py instead")

    class FakeServer:
        def __init__(self,*args,**kwargs):
            self.functions={}
        def tool(self):
            def registrar(fn):
                self.functions[fn.__name__]=fn
                return fn
            return registrar

    class FakeResult:
        def __init__(self, data=None, error=None):
            self.is_error=error is not None
            self.structured_content=data
            self.content=[] if error is None else [types.SimpleNamespace(text=str(error))]

    class FakeClient:
        def __init__(self, server, mode=None):
            self.server=server
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            return False
        async def list_tools(self):
            result=[]
            for name,fn in self.server.functions.items():
                sig=inspect.signature(fn)
                schema={"type":"object","properties":{},"required":[],"additionalProperties":False}
                for param in sig.parameters.values():
                    schema["required"].append(param.name)
                    schema["properties"][param.name]={"type":"integer" if param.annotation is int else "string"}
                result.append(types.SimpleNamespace(name=name, description=fn.__doc__,input_schema=schema))
            return types.SimpleNamespace(tools=result)
        async def call_tool(self,name,args):
            if name not in self.server.functions:
                return FakeResult(error="No such tool")
            tools=await self.list_tools()
            schema=next(t.input_schema for t in tools.tools if t.name==name)
            try:
                jsonschema.validate(args,schema)
                return FakeResult(data=self.server.functions[name](**args))
            except Exception as exc:
                return FakeResult(error=exc)

    fake_mcp=types.ModuleType("mcp")
    fake_mcp_client=types.ModuleType("mcp.client")
    fake_mcp_client.Client=FakeClient
    fake_mcp_server=types.ModuleType("mcp.server")
    fake_mcp_mcpserver=types.ModuleType("mcp.server.mcpserver")
    fake_mcp_mcpserver.MCPServer=FakeServer
    for name,mod in {"mcp":fake_mcp,"mcp.client":fake_mcp_client,"mcp.server":fake_mcp_server,"mcp.server.mcpserver":fake_mcp_mcpserver}.items():
        monkeypatch.setitem(sys.modules,name,mod)
    sys.modules.pop("server",None)
    sys.modules.pop("experiment",None)
    exp=importlib.import_module("experiment")
    from agents import ScriptedDiagnosticAgent
    from benchmarks import inventory_tasks
    from taxonomy import FAULTS,CONDITIONS
    rows=[]
    for condition in CONDITIONS:
        for fault in FAULTS:
            row=asyncio.run(exp.run_trial(ScriptedDiagnosticAgent(),inventory_tasks()[0],condition,fault,"schema_diff",2))
            expected=(fault=="none" or (fault in ("transient_api","transient_timeout","transient_rate_limit") and condition!="no_verification") or condition=="closed_loop")
            assert bool(row["task_completed"])==expected, (condition,fault,row["last_error"])
            rows.append(row)
            assert row["total_tokens"] is None
            if fault=="none":
                assert row["retry_count"]==0
    exp.persist(tmp_path,rows,{"completion_status":"mock_only"})
    assert (tmp_path/"trials.csv").is_file()
    assert (tmp_path/"summary.csv").is_file()
    assert (tmp_path/"preinjection_failure_frequency.csv").is_file()
    import analyse
    import make_figures
    analyse.main(tmp_path)
    make_figures.main(tmp_path)
    assert (tmp_path/"analysis"/"RQ4_feedback_formats.csv").is_file()
    assert (tmp_path/"figures"/"completion_by_fault.png").is_file()

    # Integration of native Ollama tool-call parsing + feedback + mock MCP transport.
    # This is a MOCK, not empirical LLM evidence; the real model must be tested on Windows.
    import httpx
    from agents import OllamaAgent
    async def fake_ollama_request(request):
        sent=json.loads(request.content)
        instruction=sent["messages"][1]["content"]
        if "CURRENT ACTION: Reserve exactly" in instruction:
            tool="reserve_stock"
            args={"sku":"PEN","quantity":3}
        else:
            tool="check_stock"
            args={"sku":"PEN"}
        return httpx.Response(200,json={"message":{"tool_calls":[{"function":{"name":tool,"arguments":args}}]},
                                        "prompt_eval_count":45,"eval_count":9})
    agent=OllamaAgent(model="qwen2.5:1.5b")
    asyncio.run(agent.aclose())
    agent.client=httpx.AsyncClient(transport=httpx.MockTransport(fake_ollama_request))
    llm_simulated=asyncio.run(exp.run_trial(agent,inventory_tasks()[0],"closed_loop","stale_schema","schema_diff",2))
    assert llm_simulated["task_completed"]==1
    assert llm_simulated["injected_fault_recovered"]==1
    assert llm_simulated["total_tokens"]==4*(45+9)
    asyncio.run(agent.aclose())

    sys.modules.pop("experiment",None)
    sys.modules.pop("server",None)
