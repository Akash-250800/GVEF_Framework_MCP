"""Model-generated MCP tool proposals via FREE local Ollama; no paid API or account.

The model chooses a tool; the host executes it ONLY through MCP. Diagnostics
are separately labelled as scripted and are not valid LLM research outcomes.
"""
import json
import os

import httpx


class ScriptedDiagnosticAgent:
    mode = "diagnostic"
    model = "NON_LLM_SCRIPTED_DIAGNOSTIC"

    async def generate(self, task, step, catalog, feedback="", history=()):
        # Only tests plumbing. NEVER use as evidence of LLM reliability/recovery.
        return json.dumps({"tool": step["expected_tool"], "args": step["expected_args"]}), None


class OllamaAgent:
    mode = "llm"

    def __init__(self, model="qwen2.5:1.5b", base_url=None, timeout=240, temperature=0):
        self.model = model
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        # Ollama's local API requires no key, log-in, or cloud service.
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10))
        self.temperature = temperature

    async def generate(self, task, step, catalog, feedback="", history=()):
        """Request genuine tool call using Ollama /api/chat and MCP-discovered schemas."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or t.name,
                    "parameters": t.input_schema,
                },
            }
            for t in catalog.values()
        ]
        system = (
            "You are a tool-use agent. Select exactly ONE available function to perform "
            "the CURRENT ACTION. Produce one tool call with correct JSON arguments. "
            "Never simulate tool execution. If you cannot issue a native tool call, "
            'respond with only {"tool":"name","args":{...}} valid JSON and no prose. '
            "On feedback, reconsider the failed candidate and produce a CORRECTED call."
        )
        user = (
            f"OVERALL TASK: {task['description']}\n"
            f"CURRENT ACTION: {step['instruction']}\n"
            f"MCP TOOL CATALOG: {json.dumps([{'name': t.name, 'description': t.description, 'input_schema': t.input_schema} for t in catalog.values()], ensure_ascii=False)}\n"
            f"RECENT ACTIONS AND ERRORS: {json.dumps(list(history)[-4:], ensure_ascii=False, default=str)}\n"
            f"CORRECTIVE FEEDBACK: {feedback or 'none'}\n"
            "Generate exactly one tool call now."
        )
        try:
            response = await self.client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "tools": tools,
                    "stream": False,
                    "options": {"temperature": self.temperature, "num_predict": 256, "num_ctx": 4096},
                },
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                "Ollama is not running. Start the Ollama Windows app; then run "
                "'ollama pull qwen2.5:1.5b' and 'python check_ollama.py'."
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise RuntimeError(
                    f"Ollama could not find model {self.model!r}. "
                    f"Run: ollama pull {self.model}"
                ) from exc
            raise RuntimeError(f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text[:350]}") from exc

        data = response.json()
        message = data.get("message", {}) or {}
        calls = message.get("tool_calls") or []
        if len(calls) == 1:
            func = calls[0].get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    # Keep malformed output so the verifier can measure it.
                    args = args
            proposal = json.dumps({"tool": func.get("name"), "args": args}, ensure_ascii=False)
        elif len(calls) > 1:
            # One tool call is the experimental contract; flag violations.
            proposal = json.dumps({"error": "multiple_tool_calls", "calls": calls}, ensure_ascii=False)
        else:
            # A 1.5B model may return raw JSON instead of native tool_calls.
            # Ollama-compatible models may use the native function-call field
            # names (name/arguments) even when emitting text instead of a
            # structured tool_calls response. Map this *valid* representation
            # to the framework's tool/args envelope. This is protocol-format
            # adaptation, not agent self-correction; malformed values must
            # still reach the verifier unchanged.
            proposal = (message.get("content") or "").strip()
            try:
                content_call = json.loads(proposal)
            except (json.JSONDecodeError, TypeError):
                pass
            else:
                if (
                    isinstance(content_call, dict)
                    and isinstance(content_call.get("name"), str)
                    and isinstance(content_call.get("arguments"), dict)
                    and "tool" not in content_call
                    and "args" not in content_call
                ):
                    proposal = json.dumps(
                        {"tool": content_call["name"], "args": content_call["arguments"]},
                        ensure_ascii=False,
                    )

        input_count = data.get("prompt_eval_count")
        output_count = data.get("eval_count")
        usage = None if input_count is None or output_count is None else {
            "input": int(input_count), "output": int(output_count)
        }
        return proposal, usage

    async def aclose(self):
        await self.client.aclose()


def new_agent(mode, model):
    if mode == "diagnostic":
        return ScriptedDiagnosticAgent()
    if mode in ("llm", "ollama"):
        return OllamaAgent(model)
    raise ValueError(f"Unsupported mode: {mode}")
