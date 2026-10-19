"""One command to confirm the chosen local model is installed and generating."""
import argparse
import os
import sys
import httpx


def check(base_url=None, model="qwen2.5:1.5b", client=None):
    url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    conn = client or httpx.Client(timeout=150)
    try:
        tags = conn.get(f"{url}/api/tags")
        tags.raise_for_status()
        names = [m.get("name", "") for m in tags.json().get("models", [])]
        if model not in names and not any(n.split(":")[0] == model.split(":")[0] and model.endswith(":latest") for n in names):
            raise RuntimeError(f"Model {model!r} not found. Run: ollama pull {model}\nInstalled: {names}")
        resp = conn.post(f"{url}/api/chat", json={
            "model": model, "stream": False,
            "messages": [{"role": "user", "content": "Reply with just the word READY"}],
            "options": {"num_predict": 30, "temperature": 0, "num_ctx": 1024},
        })
        resp.raise_for_status()
        data = resp.json()
        if not (data.get("message") or {}).get("content"):
            raise RuntimeError("Ollama responded but did not return text")
        print("OLLAMA CONNECTION: PASS")
        print("MODEL:", model)
        print("SAMPLE RESPONSE:", data["message"]["content"].strip())
        print("TOKENS:", data.get("prompt_eval_count", "N/A"), "+", data.get("eval_count", "N/A"))
        return True
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise RuntimeError("Ollama is not running. Open the Ollama Windows app and retry.") from exc
    finally:
        if client is None:
            conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="qwen2.5:1.5b")
    opts = p.parse_args()
    try:
        check(model=opts.model)
    except Exception as error:
        print(f"OLLAMA CONNECTION: FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
