"""Full MCP thesis experiment suite: baseline, feedback ablation, retry-budget ablation.

Each trial uses a fresh MCP server, model-generated proposals (LLM mode), and
controlled first-attempt fault injection. Diagnostic mode is NEVER LLM evidence.
"""
import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from taxonomy import FAULTS, CONDITIONS, FEEDBACKS, Fault, inject
from agents import new_agent
from benchmarks import inventory_tasks, load_bfcl, make_bfcl_server
from server import make_server
from verification import parse_proposal, validate, unwrap_mcp_reply
from feedback import render_feedback


def is_correct_output(step, proposal, output):
    if "bfcl_gold" in step:
        return any(proposal == expected for expected in step["bfcl_gold"])
    return output == step.get("expected_output")


def is_tool_mutating(step, call):
    return step.get("mutating", False) or call.get("tool") in {"reserve_stock", "release_stock", "delete_record", "update_record"}


async def run_trial(agent, task, condition, fault, feedback_style, retry_budget, rep=1):
    """Retry budget counts *additional* attempts. All policies start with one attempt."""
    from mcp.client import Client
    server = make_bfcl_server(task) if task["source"] == "bfcl_single_call" else make_server()
    started = perf_counter()
    events=[]
    attempts=0
    completed=0
    total_tokens=0 if agent.mode == "llm" else None
    token_complete=bool(agent.mode == "llm")
    injected=False
    natural_errors=0
    spontaneous_categories=[]
    generated_calls=0
    actual_retries=0
    recovered=False
    breaker_open=False
    last_failure=""
    session_history=[]
    extra_attempts = 0 if condition == "no_verification" else retry_budget
    # Force JSON-RPC in-process transport rather than direct function dispatcher.
    # A standalone Streamable HTTP deployment is provided as a separate smoke test.
    async with Client(server) as client:
        catalog = {t.name: t for t in (await client.list_tools()).tools}
        for step_index, step in enumerate(task["steps"]):
            raw_candidate=None
            success=False
            feedback_text=""
            previous_proposal=""
            for attempt_idx in range(extra_attempts + 1):
                attempt_number=attempt_idx + 1
                attempts += 1
                if attempt_idx > 0:
                    actual_retries += 1
                entry={"task":task["id"],"replicate":rep,"step":step_index+1,
                       "attempt":attempt_number,"condition":condition,"fault":fault,
                       "feedback_format":feedback_style,"feedback_received":feedback_text,
                       "stage":"","result":""}
                if attempt_idx == 0 or condition == "closed_loop":
                    try:
                        raw_candidate, usage = await agent.generate(task, step, catalog, feedback_text, session_history)
                    except Exception as exc:
                        last_failure=f"Model generation failed: {type(exc).__name__}: {str(exc)[:500]}"
                        entry.update(stage="generation",result="error",detail=last_failure)
                        events.append(entry)
                        # Don't claim this is a tool-call failure; API outage/invalid credentials.
                        break
                    generated_calls += 1
                    if agent.mode == "llm":
                        if usage is None:
                            token_complete=False
                        else:
                            total_tokens += usage["input"] + usage["output"]
                    # RQ1 spontaneous candidate errors are inspected BEFORE fault injection.
                    first_call, first_error=parse_proposal(raw_candidate)
                    if first_error is None:
                        first_error=validate(first_call,catalog,step)
                    if first_error is not None:
                        natural_errors+=1
                        spontaneous_categories.append(first_error.category)
                    if step_index == task["fault_step"] and attempt_idx == 0 and fault != "none":
                        original_candidate=raw_candidate
                        raw_candidate=inject(raw_candidate,fault,step,catalog)
                        # Only count a payload fault if its bytes actually changed.
                        if fault not in ("transient_api", "transient_timeout", "transient_rate_limit"):
                            injected = raw_candidate != original_candidate
                previous_proposal=raw_candidate
                entry["proposal"] = (raw_candidate or "")[:4000]
                call, err=parse_proposal(raw_candidate)
                if err:
                    entry.update(stage="parse",result="rejected",error=err.dict())
                elif condition == "closed_loop":
                    err=validate(call,catalog,step, schema_enabled=True,safety_enabled=True)
                    if err:
                        entry.update(stage="preflight",result="rejected",error=err.dict())
                if err is None and call is not None:
                    if step_index == task["fault_step"] and attempt_idx == 0 and fault in ("transient_api", "transient_timeout", "transient_rate_limit"):
                        mapping={
                           "transient_api": ("http_503", "Injected temporary upstream HTTP 503 failure", "HTTPError: 503 Service Unavailable"),
                           "transient_timeout": ("api_timeout", "Injected upstream network timeout", "TimeoutError: request timed out"),
                           "transient_rate_limit": ("http_429", "Injected upstream API rate limit", "HTTPError: 429 Too Many Requests"),
                        }
                        code, message, trace=mapping[fault]
                        injected=True
                        err=Fault("transient_api", code, message, trace=trace, injected=True)
                        entry.update(stage="transport_injection",result="rejected",error=err.dict())
                    else:
                        try:
                            reply=await client.call_tool(call["tool"],call["args"])
                            payload, err=unwrap_mcp_reply(reply)
                        except Exception as exc:
                            err=Fault("execution_failure",type(exc).__name__,str(exc)[:500],trace="".join(traceback.format_exception(exc))[-2400:])
                            payload=None
                        if err is not None:
                            entry.update(stage="execution",result="error",error=err.dict())
                        elif not is_correct_output(step,call,payload):
                            err=Fault("semantic_failure", "oracle_mismatch", "Tool call returned a result that does not satisfy the task's independent success criterion",actual=repr(payload)[:400])
                            entry.update(stage="evaluation",result="wrong_result",error=err.dict(),output=payload)
                            # A state-changing operation may have COMMITTED. Do not blindly replay.
                            if is_tool_mutating(step,call):
                                entry["unsafe_to_retry"] = True
                        else:
                            success=True
                            entry.update(stage="evaluation",result="success",output=payload)
                            events.append(entry)
                            if step_index==task["fault_step"] and fault != "none" and attempt_idx>0:
                                recovered=True
                            session_history.append({"instruction":step["instruction"],"proposal":call,"output":payload})
                            completed += 1
                            break
                events.append(entry)
                if err:
                    last_failure=err.message
                    if condition == "closed_loop":
                        feedback_text=render_feedback(err,feedback_style)
                        entry["feedback_sent"] = feedback_text
                        session_history.append({"failed_call":previous_proposal,"feedback":feedback_text})
                    if entry.get("unsafe_to_retry"):
                        breaker_open=True
                        last_failure="Unsafe to retry state-changing operation without compensating rollback; escalation required"
                        break
                if condition == "no_verification":
                    break
            if not success:
                breaker_open=True
                events.append({"task":task["id"],"step":step_index+1,"stage":"circuit_breaker",
                               "result":"give_up_or_escalate","retry_budget":retry_budget,
                               "reason":last_failure})
                break

    return {
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),"task_id":task["id"],"source":task["source"],
        "mode":agent.mode,"model":agent.model,"replicate":rep,"condition":condition,
        "fault":fault,"feedback_format":feedback_style if condition=="closed_loop" else "not_applicable",
        "retry_budget":retry_budget if condition != "no_verification" else 0,
        "task_completed":int(completed==len(task["steps"])),"completed_steps":completed,
        "injected_fault":int(injected),"injected_fault_recovered":int(injected and recovered),
        "model_proposals":generated_calls,"spontaneous_preinjection_errors":natural_errors,
        "spontaneous_categories":spontaneous_categories,
        "tool_attempts":attempts,"retry_count":actual_retries,
        "circuit_breaker_open":int(breaker_open),
        "latency_seconds":round(perf_counter()-started,6),
        "total_tokens": total_tokens if token_complete else None,
        "token_measurement_complete":int(token_complete),"last_error":last_failure if breaker_open else "",
        "events":events,
    }


def configs(suite, conditions, faults, feedback_formats, retry_budgets):
    """Unique policy configurations; comparisons share matched tasks and injected faults."""
    plans=[]
    if suite in ("all", "baselines"):
        for f in faults:
            for c in conditions:
                if c == "closed_loop":
                    plans.append((c,f,"schema_diff",retry_budgets[0]))
                else:
                    plans.append((c,f,"not_applicable",retry_budgets[0]))
    if suite in ("all","feedback"):
        for f in faults:
            for style in feedback_formats:
                plans.append(("closed_loop",f,style,retry_budgets[0]))
    if suite in ("all","retry"):
        for f in faults:
            for budget in retry_budgets:
                for c in conditions:
                    plans.append((c,f,"schema_diff" if c=="closed_loop" else "not_applicable",budget))
    return list(dict.fromkeys(plans))


def persist(destination, rows, manifest):
    destination.mkdir(parents=True,exist_ok=True)
    base=["timestamp_utc","task_id","source","mode","model","replicate","condition","fault","feedback_format", "retry_budget",
          "task_completed","completed_steps","injected_fault","injected_fault_recovered","model_proposals",
          "spontaneous_preinjection_errors","tool_attempts","retry_count","circuit_breaker_open","latency_seconds",
          "total_tokens","token_measurement_complete","last_error"]
    with (destination/"trials.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=base); writer.writeheader()
        writer.writerows({key:r.get(key) for key in base} for r in rows)
    with (destination/"attempt_events.jsonl").open("w",encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row,ensure_ascii=False,default=str)+"\n")
    summary=[]; groups=defaultdict(list)
    for row in rows:
        groups[(row["condition"],row["fault"],row["feedback_format"],row["retry_budget"])].append(row)
    for key, records in sorted(groups.items()):
        fault=key[1]; injected=[r for r in records if r["injected_fault"]]
        tokens=[r["total_tokens"] for r in records if r["total_tokens"] is not None]
        model_proposals=sum(r["model_proposals"] for r in records)
        summary.append({
          "condition":key[0],"fault":fault,"feedback_format":key[2],"retry_budget":key[3],
          "n":len(records),"completion_rate":sum(r["task_completed"] for r in records)/len(records),
          "recovery_rate":sum(r["injected_fault_recovered"] for r in injected)/len(injected) if injected else "N/A",
          "mean_latency_seconds":statistics.mean(r["latency_seconds"] for r in records),
          "mean_retries":statistics.mean(r["retry_count"] for r in records),
          "mean_tokens":statistics.mean(tokens) if len(tokens)==len(records) else "N/A",
          "preinjection_error_rate":sum(r["spontaneous_preinjection_errors"] for r in records)/model_proposals if model_proposals else "N/A",
          "circuit_breaker_rate":sum(r["circuit_breaker_open"] for r in records)/len(records),
        })
    # RQ1: naturally generated failures, BEFORE intervention or injection.
    # These are rates within the selected study tasks; not real-world prevalence.
    observed=defaultdict(int)
    for r in rows:
        for category in r.get("spontaneous_categories", []):
            observed[category] += 1
    with (destination/"preinjection_failure_frequency.csv").open("w",newline="",encoding="utf-8") as fh:
        writer=csv.DictWriter(fh,fieldnames=["failure_category","count","all_model_proposals","observed_rate_per_proposal"])
        writer.writeheader()
        proposals=sum(r["model_proposals"] for r in rows)
        for category,count in sorted(observed.items()):
            writer.writerow({"failure_category":category,"count":count,"all_model_proposals":proposals,
                             "observed_rate_per_proposal": count/proposals if proposals else "N/A"})
    if summary:
        with (destination/"summary.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    (destination/"manifest.json").write_text(json.dumps(manifest,indent=2,default=str),encoding="utf-8")
    return summary


async def run(args):
    if args.benchmark=="inventory":
        tasks=inventory_tasks()[:args.tasks]
        skipped=[]
    else:
        tasks, skipped=load_bfcl(args.bfcl_questions,args.bfcl_answers,args.tasks)
    if not tasks:
        raise ValueError("No tasks selected")
    styles=FEEDBACKS if args.feedback_formats=="all" else (args.feedback_formats,)
    faults=FAULTS if args.faults=="all" else tuple(args.faults.split(","))
    for f in faults:
        if f not in FAULTS:
            raise ValueError(f"Unknown fault {f!r}")
    budgets=tuple(int(x) for x in args.retry_budgets.split(","))
    if any(x<0 or x>10 for x in budgets):
        raise ValueError("Retry budgets must be 0 through 10")
    # A missing model must stop the program, not produce a table of false task failures.
    if args.mode in ("llm", "ollama"):
        from check_ollama import check
        check(model=args.model)
    agent=new_agent(args.mode,args.model)
    conditions=CONDITIONS
    plan=configs(args.suite,conditions,faults,styles,budgets)
    total=len(tasks)*len(plan)*args.replicates
    manifest={"start_utc":datetime.now(timezone.utc).isoformat(),"mode":args.mode,"model":agent.model,
              "benchmark":args.benchmark,"benchmark_question_file":args.bfcl_questions,"benchmark_answer_file":args.bfcl_answers,
              "dataset_rejected_entries":skipped,"task_count":len(tasks),"task_ids":[t["id"] for t in tasks],
              "suite":args.suite,"faults":list(faults),"feedback_formats":list(styles),"retry_budgets":list(budgets),
              "replicates":args.replicates,"trial_plans":len(plan),"total_planned_trials":total,
              "token_cost_note":"Measured from live model API usage only. Not a currency cost.",
              "injection_note":"Controlled faults are synthetic; incidence in natural traffic is separately logged as pre-injection generation errors.",
              "completion_status":"in_progress"}
    out=Path(args.out)
    rows=[]
    if args.resume:
        existing_manifest = out / "manifest.json"
        existing_trials = out / "attempt_events.jsonl"
        if existing_manifest.exists() and existing_trials.exists():
            previous = json.loads(existing_manifest.read_text(encoding="utf-8"))
            keys = ("mode", "model", "benchmark", "task_ids", "suite", "faults",
                    "feedback_formats", "retry_budgets", "replicates", "total_planned_trials")
            mismatched = [key for key in keys if previous.get(key) != manifest.get(key)]
            if mismatched:
                raise ValueError("Cannot resume: settings differ from previous run: " + ", ".join(mismatched))
            with existing_trials.open(encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            print(f"RESUME: loaded {len(rows)} already-completed trial cells", flush=True)
        elif existing_manifest.exists() or existing_trials.exists():
            raise ValueError("Cannot resume: missing one of manifest.json / attempt_events.jsonl")
    elif (out / "trials.csv").exists():
        raise FileExistsError(f"Results already exist at {out}. Choose a NEW --out folder or add --resume.")
    done = {(r['replicate'], r['task_id'], r['condition'], r['fault'], r['feedback_format'], r['retry_budget']) for r in rows}
    print(f"Benchmark={args.benchmark}; mode={args.mode}; {total} planned trial cells, {len(tasks)} tasks",flush=True)
    for rep in range(1,args.replicates+1):
        for task in tasks:
            for condition,fault,style,budget in plan:
                key = (rep, task['id'], condition, fault, style if condition == 'closed_loop' else 'not_applicable', budget if condition != 'no_verification' else 0)
                if key in done:
                    continue
                row=await run_trial(agent,task,condition,fault,style,budget,rep)
                rows.append(row)
                persist(out,rows,manifest)
                count=len(rows)
                print(f"[{count}/{total}] {task['id']} {fault} {condition} fb={style} retries={budget}: {'PASS' if row['task_completed'] else 'FAIL'}",flush=True)
                if args.max_trials and count>=args.max_trials:
                    manifest["completion_status"]="intentionally_stopped_early"
                    persist(out,rows,manifest)
                    return rows
    manifest["completion_status"]="complete"
    manifest["finish_utc"]=datetime.now(timezone.utc).isoformat()
    persist(out,rows,manifest)
    print(f"Completed {len(rows)} experiment trial cells; exported {out.resolve()}")
    if hasattr(agent, "aclose"):
        await agent.aclose()
    if args.mode == "diagnostic":
        print("WARNING: Scripted diagnostic mode is a technical plumbing test, not an LLM study.")
    return rows


def cli(argv=None):
    parser=argparse.ArgumentParser(description="Full MCP closed-loop verification research experiment runner")
    parser.add_argument("--mode",choices=("diagnostic","ollama","llm"),default="diagnostic", help="Use 'ollama' for real local AI trials; 'llm' is an alias")
    parser.add_argument("--model",default="qwen2.5:1.5b")
    parser.add_argument("--benchmark",choices=("inventory","bfcl"),default="inventory")
    parser.add_argument("--bfcl-questions",default="")
    parser.add_argument("--bfcl-answers",default="")
    parser.add_argument("--tasks",type=int,default=20)
    parser.add_argument("--replicates",type=int,default=1)
    parser.add_argument("--suite",choices=("all","baselines","feedback","retry"),default="all")
    parser.add_argument("--faults",default="all",help="all or comma-separated names from taxonomy.py")
    parser.add_argument("--feedback-formats",choices=("all",*FEEDBACKS),default="all")
    parser.add_argument("--retry-budgets",default="2,0,1,3,4")
    parser.add_argument("--max-trials",type=int,default=0,help="Early-stop for smoke test; manifest says incomplete")
    parser.add_argument("--out",default="results")
    parser.add_argument("--resume",action="store_true",help="Continue a partially completed run without repeating saved trials")
    args=parser.parse_args(argv)
    if args.tasks<1 or args.replicates<1:
        parser.error("--tasks and --replicates must be >=1")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Stopped by user; rows completed so far remain saved.",file=sys.stderr)
        raise SystemExit(130)

if __name__=="__main__":
    cli()
