# MCP Thesis — Full Coding and Experimental Framework (Ollama Edition)

**Thesis brief:** *Closed-Loop Verification for Protocol-Based Agentic Workflows: Automated Error-Recovery in Model Context Protocol (MCP) Infrastructures*.

**Local model:** `qwen2.5:1.5b` through the free Ollama Windows app (native `http://127.0.0.1:11434/api/chat`). **No OpenAI account, paid API key, or cloud hosting.**

This package contains a complete **coding implementation candidate** for all **software and experiment components** described in the original thesis proposal, including all four research questions. **The source files are not proof of successful deployment or completed empirical research.** Real Ollama and real MCP SDK integration must pass on the user's Windows laptop before findings can be reported. No results are fabricated or preloaded.

## 0. Folder layout (important)

Put **all files in this ZIP directly** inside `E:\MCP-Thesis` beside your existing `.venv` folder. Do not create a second project folder and **do not put project files inside `.venv`**.

```text
E:\MCP-Thesis\
    .venv\                  (you created this already; not included in ZIP)
    server.py
    agents.py
    experiment.py
    verification.py
    feedback.py
    taxonomy.py
    benchmarks.py
    download_bfcl.py
    check_ollama.py
    analyse.py
    make_figures.py
    serve_http.py
    http_smoke_test.py
    requirements.txt
    START_WINDOWS.bat
    tests\
    data\
```

## 1. Windows commands — perform in order

Open **Anaconda Prompt** (yes, Anaconda Prompt is fine). Execute commands **one at a time**.

```bat
cd /d E:\MCP-Thesis
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
```

If any command fails, stop and inspect the full error. Real SDK tests must be run locally; they cannot be substituted by offline tests.

**Install Ollama for Windows** from https://ollama.com/download/windows. Open Ollama and make sure it is running in the background. You do not need to log in or use any paid account. In Anaconda Prompt run:

```bat
ollama pull qwen2.5:1.5b
python check_ollama.py
```

**Note:** `ollama run qwen2.5:1.5b` also downloads the model, but it enters an interactive chat. For automatic Python experiments, `ollama pull` plus the running Ollama application is sufficient. The experiments communicate with the same model through its local API. You can use the `ollama run` command to chat manually if you wish, but you do not need to leave that chat open.

If Ollama has not launched automatically, open **Ollama** from the Windows Start menu. `python check_ollama.py` checks both installation and model response, and fails with instructions if something is missing.

## 2. First genuine Ollama/MCP experiment (three conditions)

Start with a small pilot to confirm that the tool-calling agent works. This is **real model-generated data**, not a scripted simulation:

```bat
python experiment.py --mode ollama --model qwen2.5:1.5b --tasks 1 --suite baselines --faults type_mismatch --out results_ollama_pilot
```

The pilot should generate `results_ollama_pilot\trials.csv`, `summary.csv`, `attempt_events.jsonl`, `preinjection_failure_frequency.csv`, and `manifest.json`. Individual `FAIL` results can be genuine experimental failures. The program should finish without a Python traceback. If it cannot connect to Ollama, it should terminate before creating fake research trial rows.

## 3. All failure categories, policy comparisons, feedback formats, and retry budgets

```bat
python experiment.py --mode ollama --model qwen2.5:1.5b --tasks 20 --replicates 3 --suite all --out results_ollama_full
```

**WARNING:** This is a large experiment. On an 8 GB RAM laptop it may take many hours or longer, depending on CPU speed and model performance. No requirement is skipped by the code; however, completing all planned trials is a separate practical question. The manifest explicitly says `in_progress`, `intentionally_stopped_early` or `complete`. Interrupted/early-stopped runs cannot be called complete.

To continue an interrupted run **with the same settings** without repeating saved trial cells:

```bat
python experiment.py --mode ollama --model qwen2.5:1.5b --tasks 20 --replicates 3 --suite all --out results_ollama_full --resume
```

Do **not** delete the `results_ollama_full` folder. `--resume` cannot be used to change settings halfway through an experiment. To change parameters, use a new output directory.

For a **separate technical diagnostic** that uses a scripted agent (NOT LLM evidence):

```bat
python experiment.py --mode diagnostic --tasks 20 --suite all --out results_diagnostic
```

## 4. Generate actual data analysis and graphs

```bat
python analyse.py --results results_ollama_full
python make_figures.py --results results_ollama_full
```

Outputs are located in `results_ollama_full\analysis` and `results_ollama_full\figures`. Results are computed only from recorded trials. Metrics with unavailable model token usage are not invented.

## 5. Adapt an existing published benchmark (BFCL v3, simple single-call)

The proposal **prefers adapting an existing benchmark**. This code also includes a 20-task isolated **multi-tool inventory sandbox**, plus a real **BFCL v3 subset adapter**. To obtain a genuine published benchmark without paying, download the official Apache-2.0-licensed BFCL v3 simple subset:

```bat
python download_bfcl.py
```

This downloads question and gold JSONL files to `data\bfcl_v3_simple\`, and records source URL and SHA256 hashes. Internet is needed **only for this download**, not to run the model afterward.

Then run the BFCL adapter across its supported **single-call** cases:

```bat
python experiment.py --mode ollama --benchmark bfcl --bfcl-questions data\bfcl_v3_simple\questions.jsonl --bfcl-answers data\bfcl_v3_simple\answers.jsonl --tasks 20 --suite all --out results_bfcl
```

BFCL defines more complex test categories (multi-turn/parallel/specialised AST). Those are **not claimed to be part of this single-call adapter**, and this package does **not claim official BFCL leaderboard scoring**. The 20 multi-tool inventory tasks supply the end-to-end workflow required for this thesis. BFCL supplies an independently sourced tool-schema benchmark. Benchmarks are selected/recorded, not invented as real-world traffic.

## 6. Real local MCP server transport proof

This is **not cloud deployment**. It proves MCP communication over local Streamable HTTP as well as the in-memory MCP used by experimental trials.

First Anaconda Prompt:

```bat
cd /d E:\MCP-Thesis
.venv\Scripts\activate
python serve_http.py
```

Keep the first prompt running. Open a second **Anaconda Prompt**:

```bat
cd /d E:\MCP-Thesis
.venv\Scripts\activate
python http_smoke_test.py
```

Expected: `LOCAL MCP HTTP CONNECTION: SUCCESS`. Use `Ctrl+C` to stop the server in the first window.

## 7. Traceability — coding items from the original brief

| Thesis requirement | Code |
|---|---|
| Real LLM agent generating MCP calls (RQ1–RQ4) | `agents.py` native Ollama `/api/chat` tool calling with MCP-discovered schemas |
| Generate → Verify → Eval → Feedback | `experiment.py`, `verification.py`, `feedback.py` |
| Intermediate sandbox; validate before state-changing actions | `verification.py`, `server.py` synthetic state and closed-loop preflight |
| JSON payload structure and tool schema validation | `verification.py` via `jsonschema`; MCP tool discovery |
| Safety invariants and semantically wrong tool checks | `verification.py`; independent task intent check |
| Five error families | `taxonomy.py`: malformed payload, parameter type, stale/misread schema, transient API, wrong tool |
| Transient timeout, 429, 503 | `taxonomy.py`, `experiment.py` |
| Automatic error feedback and self-correction | `agents.py`, `feedback.py`, `experiment.py` regeneration |
| Three feedback formats (RQ4) | `feedback.py`: raw trace, schema diff, natural language |
| No verification / naive retry / closed loop (RQ2) | `experiment.py` conditions and shared task matrix |
| Bounded retries, circuit breaker, give-up/escalation | `experiment.py` |
| Controlled fault injection at known rates | `taxonomy.py`, `experiment.py` |
| End-to-end multi-tool tasks | `benchmarks.py`: stock-check → reservation → confirmation across 20 tasks |
| Existing tool-use benchmark adaptation | `download_bfcl.py`, `benchmarks.py` BFCL single-call adapter |
| Identical injected-fault/task schedules | `experiment.py` policy matrix and separate sandbox per trial |
| Pre-injection natural model failure observations (RQ1) | `experiment.py`, `preinjection_failure_frequency.csv` |
| Task completion % and recovery % | `experiment.py`, `summary.csv` |
| Token counts (including generation and feedback) | `agents.py` real Ollama token counters, `experiment.py` |
| Latency and retry count/loop depth | `experiment.py` per-trial metrics and events |
| Reliability vs token-cost trade-off (RQ3) | `analyse.py`, `make_figures.py` |
| Feedback format comparison (RQ4) | `analyse.py`, `make_figures.py` |
| Retry-budget / circuit-breaker ablation (RQ3) | `experiment.py`, `analyse.py`, `make_figures.py` |
| Open inspectable source and reproducible settings | All `.py` source; `manifest.json`; hashes for BFCL data |
| Actual local MCP protocol | `server.py`, `experiment.py`, `serve_http.py`, `http_smoke_test.py` |
| Automated tests | `tests/`, run with `python -m pytest -q` |

## 8. Results accuracy and restrictions

1. The experiment's initial tool calls and all corrective attempts come from **real Qwen model generations** in `--mode ollama`; `--mode diagnostic` uses known answers exclusively for checking plumbing, marked **NOT_LLM_EVIDENCE**.
2. The **independent success oracle** checks the result after tool execution. The closed-loop validator gets intended tool requirements/safety rules, not exact ground-truth parameters.
3. Controlled network faults emulate timeouts/429/503 at the agent-to-tool boundary. They are not real WAN outages.
4. Experimental failures are scientifically valid outcomes, not proof the software is broken.
5. **RQ1 frequencies are measured in the selected test/model setup before injection**, not general real-world MCP failure prevalence. The proposal asks about realistic conditions; generalisation requires additional empirical sampling.
6. A mutating action with a possibly committed wrong result triggers escalation rather than unsafe blind replay.
7. If token counters are missing, token-cost results are recorded as unavailable, **never silently replaced with zero**.
8. The code is free and uses an 8 GB machine-compatible *small-model starting option*; model speed, accuracy, and complete-run duration cannot be guaranteed without running it on that laptop.
9. The ZIP excludes `.venv` and model weights intentionally. They reside on your laptop and are not source code. Model weights are downloaded by `ollama pull`.

## 9. Authoritative reference links

- MCP Python SDK v2: https://py.sdk.modelcontextprotocol.io/
- MCP client guide: https://py.sdk.modelcontextprotocol.io/client/
- Ollama native API: https://github.com/ollama/ollama/blob/main/docs/api.md
- Ollama Windows download: https://ollama.com/download/windows
- BFCL official dataset: https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard
