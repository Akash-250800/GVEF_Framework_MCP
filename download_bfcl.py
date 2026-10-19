"""Download the official Apache-2.0 BFCL v3 simple subset; no account needed."""
from pathlib import Path
from urllib.request import urlopen, Request
import hashlib
import json

BASE = "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main"
FILES = {
    "questions": "BFCL_v3_simple.json",
    "answers": "possible_answer/BFCL_v3_simple.json",
}


def main():
    target = Path("data/bfcl_v3_simple")
    target.mkdir(parents=True, exist_ok=True)
    provenance = {"source": BASE, "license": "Apache-2.0", "files": {}}
    for label, relative in FILES.items():
        destination = target / f"{label}.jsonl"
        url = f"{BASE}/{relative}"
        print(f"Downloading {label} from official Berkeley dataset...", flush=True)
        request = Request(url, headers={"User-Agent": "MCP-thesis-research/1.0"})
        with urlopen(request, timeout=90) as response:
            content = response.read()
        if not content.lstrip().startswith(b'{'):
            raise RuntimeError(f"Unexpected download format from {url}")
        # Validate downloaded JSONL before saving.
        rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
        if not rows or not all(isinstance(x,dict) and x.get("id") for x in rows):
            raise RuntimeError(f"Missing/invalid BFCL entries in {label}")
        destination.write_bytes(content)
        provenance["files"][label] = {"url": url, "sha256": hashlib.sha256(content).hexdigest(), "entries": len(rows)}
        print(f"Saved {destination} ({len(rows)} entries)", flush=True)
    (target/"SOURCE.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    print("BFCL DOWNLOAD: SUCCESS")
    print("BFCL paths: data/bfcl_v3_simple/questions.jsonl and data/bfcl_v3_simple/answers.jsonl")


if __name__ == '__main__':
    main()
