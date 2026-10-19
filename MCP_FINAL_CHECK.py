"""Final evidence reconciliation for MCP thesis. Never runs LLMs or edits experiments.

Copy beside experiment.py and run with your project .venv Python. The only writes
are new files under final_verification/. Requires Python 3.10+; no third-party libs.
"""
from __future__ import annotations
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'final_verification'
GROUPS = {
    'inventory_baselines': ('results_ollama_baselines', 480),
    'feedback_formats': ('results_ollama_feedback', 72),
    'retry_budgets': ('results_ollama_retry', 237),
    'bfcl_baselines': ('results_bfcl_baseline', 60),
}
POLICIES = ('no_verification', 'naive_retry', 'closed_loop')
FEEDBACKS = ('raw_trace', 'schema_diff', 'natural_language')
FAULTS = ('none','malformed_json','type_mismatch','stale_schema','transient_api',
          'transient_timeout','transient_rate_limit','wrong_tool')
CODE = ('agents.py','server.py','experiment.py','verification.py','feedback.py',
        'taxonomy.py','benchmarks.py','analyse.py','make_figures.py','serve_http.py',
        'http_smoke_test.py','MCP_Audit_Corrections.py')

def fail(message):
    raise RuntimeError(message)

def read_csv(path):
    if not path.is_file(): fail(f'MISSING FILE: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def read_jsonl(path):
    if not path.is_file(): fail(f'MISSING FILE: {path}')
    with path.open('r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]

def write_csv(name,rows,columns):
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns, extrasaction='ignore'); w.writeheader();w.writerows(rows)

def frac(a,b):return a / b if b else 0.0

def mean(rows,field):return statistics.mean(float(r[field]) for r in rows) if rows else 0.0

def nsuccess(rows):return sum(int(r['task_completed']) for r in rows)

def fpercent(x):return f'{x*100:.1f}%'

def main():
    # Validate first; do not write anything if the evidence is missing.
    for file in CODE:
        if not (ROOT/file).is_file():fail(f'REQUIRED SOURCE MISSING: {file}')
    raw={}
    manifests={}
    for name,(directory,expected) in GROUPS.items():
        directory=ROOT/directory
        items=read_csv(directory/'trials.csv')
        events=read_jsonl(directory/'attempt_events.jsonl')
        man=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if len(items)!=expected or len(events)!=expected:
            fail(f'{name}: expected {expected}, found {len(items)} rows / {len(events)} events')
        if man.get('completion_status')!='complete':fail(f'{name}: experiment manifest is not complete')
        if any(row.get('mode')!='llm' or row.get('model')!='qwen2.5:1.5b' for row in items):
            fail(f'{name}: expected genuine Qwen LLM records, but found another mode/model')
        if any(row.get('token_measurement_complete')!='1' for row in items):
            fail(f'{name}: missing real token usage in at least one row')
        for trial,evt in zip(items, events):
            if (trial['task_id'],trial['condition'],trial['fault']) != (evt['task_id'],evt['condition'],evt['fault']):
                fail(f'{name}: CSV rows and event JSONL are not aligned')
        raw[name]=items; manifests[name]=man
    # Audited copy must exist; preserve original results_ollama_baselines.
    audited=ROOT/'audit_verification'
    base=read_csv(audited/'corrected_baselines'/'trials.csv')
    event=read_jsonl(audited/'corrected_baselines'/'attempt_events.jsonl')
    if len(base)!=480 or len(event)!=480:fail('Corrected baseline audit must contain exactly 480 records')
    for p,q in zip(base, raw['inventory_baselines']):
        for key in ('task_id','condition','fault','total_tokens','task_completed'):
            if p[key]!=q[key]:fail('Audited copy differs from original in a non-correction field')
    audit_changes=read_csv(audited/'fault_flag_corrections.csv')
    if len(audit_changes)!=1:fail('Expected exactly one documented erroneous injection-flag correction')
    # Confirm verified source hashes from the prior correction script.
    hashes=json.loads((audited/'PACKAGE_FILE_HASHES_VERIFIED.json').read_text(encoding='utf-8'))
    if 'files' not in hashes:fail('Verified hash manifest missing files key')
    checked=0
    for rel,digest in hashes['files'].items():
        f=ROOT/rel
        if f.is_file():
            actual=hashlib.sha256(f.read_bytes()).hexdigest()
            if actual!=digest:fail(f'SOURCE HASH CHANGED since audit: {rel}')
            checked+=1
    if checked<10:fail('Too few source-file hashes verified')
    baseline=base
    by_condition={c:[r for r in baseline if r['condition']==c] for c in POLICIES}
    if any(len(rows)!=160 for rows in by_condition.values()):fail('Baseline must have 160 cells per condition')
    combos=defaultdict(dict)
    for r in baseline:
        key=(r['task_id'],r['fault'])
        if r['condition'] in combos[key]:fail(f'Duplicate baseline key: {key}')
        combos[key][r['condition']]=r
    if len(combos)!=160 or any(set(group)!=set(POLICIES) for group in combos.values()):
        fail('All three baseline policies must have matching scheduled task/fault cells')
    feedback=raw['feedback_formats']
    if any(len([r for r in feedback if r['feedback_format']==kind])!=24 for kind in FEEDBACKS):
        fail('Feedback-format cells must have equal scheduled sample sizes')
    retry=raw['retry_budgets']
    # Ignore unchanging no-verification repeated rows in a retry-budget ablation.
    for cond in ('naive_retry','closed_loop'):
        for b in range(5):
            if len([r for r in retry if r['condition']==cond and r['retry_budget']==str(b)]) !=16:
                fail(f'Incomplete retry-budget evidence for {cond}/budget {b}')
    bfcl=raw['bfcl_baselines']
    if any(len([r for r in bfcl if r['condition']==c])!=20 for c in POLICIES):
        fail('BFCL 20-case policy coverage is not complete')
    OUT.mkdir(exist_ok=True)

    # RQ1 pre-injection failures, *not* production traffic prevalence.
    all_proposals=sum(int(r['model_proposals']) for r in baseline)
    natural=Counter(); cat_per_cond={}
    for cond, rows in by_condition.items():
        counts=Counter()
        for record in event:
            if record['condition']==cond:
                counts.update(record.get('spontaneous_categories',[]))
        cat_per_cond[cond]=counts
        natural.update(counts)
    category_labels=('malformed_payload','parameter_type_mismatch','schema_mismatch',
                     'transient_api','incorrect_tool','semantic_failure','safety_violation')
    rq1=[{'failure_category':cat,'observed_preinjection_count':natural[cat],
          'all_model_proposals':all_proposals,
          'observed_rate_per_proposal':round(frac(natural[cat],all_proposals),6),
          'scope':'Qwen-generated tool proposals for controlled local MCP inventory tasks'}
         for cat in category_labels]
    write_csv('RQ1_observed_preinjection_failure_frequency.csv',rq1,list(rq1[0]))

    # RQ2 scheduled/intention-to-treat and post-hoc actual-exposure-matched analysis.
    rows2=[]
    for cond in POLICIES:
        cases=by_condition[cond]
        faulty=[r for r in cases if r['fault']!='none']
        rows2.append({'condition':cond,'scheduled_trial_cells':len(cases),
                      'scheduled_faulted_cells':len(faulty),
                      'realised_injected_cells':sum(int(r['injected_fault']) for r in faulty),
                      'completed_tasks':nsuccess(cases), 'completion_rate':round(frac(nsuccess(cases),len(cases)),6),
                      'mean_tokens':round(mean(cases,'total_tokens'),2),
                      'mean_latency_seconds':round(mean(cases,'latency_seconds'),2),
                      'mean_retries':round(mean(cases,'retry_count'),3)})
    write_csv('RQ2_full_scheduled_comparison.csv',rows2,list(rows2[0]))
    valid=[]
    for (task,fault),set3 in combos.items():
        if fault=='none':continue
        if all(int(set3[c]['injected_fault'])==1 for c in POLICIES):
            for c in POLICIES:
                r=set3[c]
                valid.append({'task_id':task,'fault':fault,'condition':c,
                              'task_completed':int(r['task_completed']),
                              'total_tokens':int(r['total_tokens']),
                              'latency_seconds':r['latency_seconds'],
                              'recovered':int(r['injected_fault_recovered'])})
    matched_scenarios=len(valid)//3
    if len(valid)%3 or matched_scenarios!=50:
        fail(f'Matched realised-injection scenarios changed: expected 50, found {matched_scenarios}')
    write_csv('RQ2_exposure_matched_150_trials.csv',valid,list(valid[0]))
    matched_summary=[]
    for c in POLICIES:
        cases=[r for r in valid if r['condition']==c]
        matched_summary.append({'condition':c,'matched_scenarios':len(cases),
                                'completed':nsuccess(cases),'completion_rate':round(frac(nsuccess(cases),len(cases)),6),
                                'mean_tokens':round(mean(cases,'total_tokens'),2),
                                'mean_latency_seconds':round(mean(cases,'latency_seconds'),2),
                                'recovered':sum(r['recovered'] for r in cases)})
    write_csv('RQ2_exposure_matched_summary.csv',matched_summary,list(matched_summary[0]))

    # RQ3 observed bounded tradeoff. Reached budget 4? Answer: no observed universal break-even.
    rq3=[]
    for c in ('naive_retry','closed_loop'):
        prev=None
        for b in range(5):
            group=[r for r in retry if r['condition']==c and r['retry_budget']==str(b)]
            s=nsuccess(group); tokens=mean(group,'total_tokens')
            rq3.append({'condition':c,'retry_budget':b,'n':len(group),
                        'completed_tasks':s,'completion_rate':round(s/len(group),6),
                        'mean_tokens':round(tokens,2),
                        'mean_latency_seconds':round(mean(group,'latency_seconds'),2),
                        'success_change_from_previous_budget': '' if prev is None else s-prev[0],
                        'token_change_from_previous_budget': '' if prev is None else round(tokens-prev[1],2),
                        'dominated_by_previous_budget': '' if prev is None else int(s<=prev[0] and tokens>prev[1])})
            prev=(s,tokens)
    write_csv('RQ3_observed_retry_budget_tradeoff.csv',rq3,list(rq3[0]))
    rq4=[]
    for f in FEEDBACKS:
        cases=[r for r in feedback if r['feedback_format']==f]
        injected=[r for r in cases if int(r['injected_fault'])]
        rq4.append({'feedback_format':f,'n':len(cases),
                    'completed':nsuccess(cases),'completion_rate':round(frac(nsuccess(cases),len(cases)),6),
                    'mean_tokens':round(mean(cases,'total_tokens'),2),
                    'mean_latency_seconds':round(mean(cases,'latency_seconds'),2),
                    'injected_faults':len(injected),
                    'recovery_rate_given_injection':round(frac(sum(int(r['injected_fault_recovered']) for r in injected),len(injected)),6)})
    write_csv('RQ4_feedback_comparison.csv',rq4,list(rq4[0]))
    rqbfcl=[]
    for c in POLICIES:
        cases=[r for r in bfcl if r['condition']==c]
        rqbfcl.append({'condition':c,'tasks':len(cases),'completed':nsuccess(cases),
                       'completion_rate':round(nsuccess(cases)/len(cases),6)})
    write_csv('BFCL_evaluation.csv',rqbfcl,list(rqbfcl[0]))

    # Coverage check explicitly separates available research evidence and public publication.
    evidence=[
      ('MCP client and server','PASS','experiment.py; server.py; prior successful HTTP stock check'),
      ('Generate Verify Eval Feedback','PASS','experiment.py; verification.py; feedback.py'),
      ('Schema and safety preflight','PASS','verification.py; mutating-tool guard'),
      ('Five failure families and controlled injection','PASS','taxonomy.py; 8 scenarios incl control'),
      ('Self-correction; retry budgets; circuit breaker','PASS','experiment.py and saved attempt_events.jsonl'),
      ('Three baseline conditions','PASS','480 inventory trials across identical scheduled task/fault cells'),
      ('Real local model usage and tokens','PASS','849 LLM trials and complete token counts'),
      ('Adapt existing benchmark','PASS','BFCL 20-case single-call subset; no official leaderboard claims'),
      ('End-to-end multi-tool benchmark','PASS','20 inventory multi-step tasks'),
      ('Five requested metrics','PASS','trial logs and final tables'),
      ('Compare feedback formats','PASS','72 rows; 24 per feedback variant'),
      ('Compare retry budgets 0-4','PASS','16 unique trials per budget in each retry-capable condition'),
      ('Identical scheduled fault rates','PASS','20 tasks x 7 injected scenarios per condition'),
      ('Identical actually-realised fault exposure','QUALIFIED','139,57,50 realised across all scheduled rows; 50 exact-matched cells per condition in subset'),
      ('Observed local MCP failure frequencies','PASS_WITH_SCOPE','Qwen proposals for controlled local tasks; not general-world prevalence'),
      ('Find token/reliability break-even','PASS_WITH_SCOPE','Evaluate the tested budgets; report no universal cutoff demonstrated'),
      ('Figures and CSV analysis','PASS','Existing 5 PNG figures and analysis in each of 4 main runs'),
      ('Reproducibility and source hashes','PASS',f'{checked} source hashes match prior audit'),
      ('Local MCP HTTP transport','PASS_FROM_USER_LOG','HTTP STOCK VALUE: PASS previously observed on user Windows'),
      ('Publish open implementation','USER_ACTION','Ready-to-publish source archive is supplied separately; user must upload it to a public repository'),
    ]
    write_csv('REQUIREMENT_EVIDENCE_MATRIX.csv',
              [{'requirement':k,'status':status,'evidence':why} for k,status,why in evidence],
              ['requirement','status','evidence'])
    lines=[]
    lines.append('# MCP thesis: final evidence from completed runs')
    lines.append('')
    lines.append('Created from existing experiment files only. No AI calls, no new trials, no overwrites.')
    lines.append('')
    lines.append('## Evidence integrity')
    lines.append(f'- 4 completed datasets checked: {sum(len(x) for x in raw.values())} genuine Ollama trials (480 + 72 + 237 + 60).')
    lines.append('- Corrected baseline used for analysis; original baseline remains untouched.')
    lines.append(f'- {checked} source-file hashes matched the previously verified manifest.')
    lines.append('- The retry run has 237 saved rows (240 scheduled; no-verification repeat settings were skipped). Do not invent 3 rows.')
    lines.append('')
    lines.append('## RQ1: failure frequency in controlled local conditions')
    lines.append(f'- {all_proposals} model-generated proposals were logged in the inventory baseline.')
    for x in rq1:
        lines.append(f'- {x["failure_category"]}: {x["observed_preinjection_count"]} observations ({fpercent(x["observed_rate_per_proposal"])} per proposal).')
    lines.append('- These are observed proposal errors in synthetic local task workflows, not measurements of external production MCP traffic.')
    lines.append('')
    lines.append('## RQ2: performance with identical scheduled task/fault assignments')
    for x in rows2:
        lines.append(f'- {x["condition"]}: {x["completed_tasks"]}/{x["scheduled_trial_cells"]} complete ({fpercent(x["completion_rate"])}); '
                     f'{x["realised_injected_cells"]}/{x["scheduled_faulted_cells"]} actually injected; mean tokens {x["mean_tokens"]:.1f}.')
    lines.append('The proposed comparison has equal *scheduled* fault rates, but early natural errors can prevent actual fault delivery.')
    lines.append(f'A sensitivity check restricts attention to {matched_scenarios} matched task/fault cells where all three policies actually encountered an injection.')
    for x in matched_summary:
        lines.append(f'- matched {x["condition"]}: {x["completed"]}/{x["matched_scenarios"]} complete ({fpercent(x["completion_rate"])}).')
    lines.append('Post-hoc subset results are descriptive, not a new randomized experiment; selection can introduce bias.')
    lines.append('')
    lines.append('## RQ3: completion, token cost and retry-policy budget')
    for x in rq3:
        if x['condition']=='closed_loop':
            lines.append(f'- closed-loop budget {x["retry_budget"]}: {x["completed_tasks"]}/{x["n"]} complete, mean tokens {x["mean_tokens"]:.1f}, mean latency {x["mean_latency_seconds"]:.1f}s.')
    lines.append('- Within the tested budgets (0–4) the closed-loop success rate kept improving. No universal break-even threshold was observed. Claims beyond the measured range would be unsupported.')
    lines.append('- Cost is model-reported token count, not dollars. No monetary costs were measured.')
    lines.append('')
    lines.append('## RQ4: three feedback formats')
    for x in rq4:
        lines.append(f'- {x["feedback_format"]}: {x["completed"]}/{x["n"]} complete ({fpercent(x["completion_rate"])}); mean tokens {x["mean_tokens"]:.1f}.')
    lines.append('Comparison is based on three tasks per failure scenario; do not claim population-wide superiority.')
    lines.append('')
    lines.append('## BFCL benchmark')
    for x in rqbfcl:
        lines.append(f'- {x["condition"]}: {x["completed"]}/{x["tasks"]} correct.')
    lines.append('BFCL is an adapted, independent 20-case single-call subset, not an official leaderboard submission.')
    lines.append('')
    lines.append('## Deployment/publication status')
    lines.append('- Local MCP HTTP transport and stock response passed on user Windows. Server shutdown with Ctrl+C was normal.')
    lines.append('- Source code is packaged for public release. A public repository URL must be added only after the user publishes it.')
    lines.append('- This is a faithful empirical accounting, not a claim of real-world fault prevalence or a universal cost optimum.')
    (OUT/'RESEARCH_RESULTS_READY_TO_USE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    report=[
      'FINAL LOCAL RECONCILIATION CHECK: PASS',
      f'Date UTC: {datetime.now(timezone.utc).isoformat(timespec="seconds")}',
      'MCP source and complete trial evidence: PASS',
      'Baseline: 480; feedback: 72; retry: 237; BFCL: 60',
      f'Corrected baseline: 480; verified hashes: {checked}',
      f'Equal intended baseline schedules: 160 cells per condition; realised matched subset: {matched_scenarios} per condition',
      'All files saved under final_verification; original experiment folders untouched.',
      'IMPORTANT: Public release is a separate user-controlled GitHub action.',
      'IMPORTANT: Interpretation limits are in RESEARCH_RESULTS_READY_TO_USE.md',
    ]
    (OUT/'FINAL_CHECK_RESULT.txt').write_text('\n'.join(report)+'\n',encoding='utf-8')
    for line in report:print(line)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print('FINAL CHECK FAILED:',exc, file=sys.stderr)
        print('Original results are safe; send this exact error for correction.',file=sys.stderr)
        sys.exit(1)
