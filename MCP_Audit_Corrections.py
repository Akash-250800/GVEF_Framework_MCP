"""Safely reconcile recorded MCP trials without repeating model experiments.

Run from E:\\MCP-Thesis after saving this script there:
    python MCP_Audit_Corrections.py

Optionally verify the live HTTP response while serve_http.py runs:
    python MCP_Audit_Corrections.py --http

Original results and pre-existing checksums are never overwritten.
"""
import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / 'audit_verification'
BASE = ROOT / 'results_ollama_baselines'
RETRY = ROOT / 'results_ollama_retry'


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    if not fields:
        raise ValueError(f'No CSV fields for {path}')
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def csv_rows(path):
    with path.open(encoding='utf-8', newline='') as fh:
        r = csv.DictReader(fh)
        return list(r), list(r.fieldnames)


def event_rows(path):
    with path.open(encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def patch_logging():
    src = ROOT / 'experiment.py'
    text = src.read_text(encoding='utf-8')
    old = '                        raw_candidate=inject(raw_candidate,fault,step,catalog)\n                        injected=True'
    new = ('                        original_candidate=raw_candidate\n'
           '                        raw_candidate=inject(raw_candidate,fault,step,catalog)\n'
           '                        # Only count a payload fault if its bytes actually changed.\n'
           '                        if fault not in ("transient_api", "transient_timeout", "transient_rate_limit"):\n'
           '                            injected = raw_candidate != original_candidate')
    marker = '                        err=Fault("transient_api", code, message, trace=trace, injected=True)'
    if old in text and marker in text:
        backup = DEST / 'backups' / 'experiment.py.original.py'
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():
            shutil.copy2(src,backup)
        text = text.replace(old,new,1)
        text = text.replace(marker,'                        injected=True\n'+marker,1)
        src.write_text(text, encoding='utf-8')
        print('CODE LOGGING: corrected; original backed up under audit_verification/backups')
    elif new in text and '                        injected=True\n'+marker in text:
        print('CODE LOGGING: already corrected; no further changes')
    else:
        raise RuntimeError('experiment.py differs from the audited file; stopped before changing it.')


def reconcile_baseline():
    original, fields = csv_rows(BASE/'trials.csv')
    detailed = event_rows(BASE/'attempt_events.jsonl')
    if len(original) != len(detailed) or len(original) != 480:
        raise RuntimeError('Unexpected baseline row count/order; no correction applied')
    changed=[]
    for flat, event in zip(original,detailed):
        key_a=(flat['task_id'],flat['condition'],flat['fault'],flat['replicate'])
        key_b=(event['task_id'],event['condition'],event['fault'],str(event['replicate']))
        if key_a != key_b:
            raise RuntimeError('Baseline CSV and JSONL records do not align; stopped')
        if flat['fault'] in ('transient_api','transient_timeout','transient_rate_limit') and flat['injected_fault']=='1':
            actual=any(evt.get('stage')=='transport_injection' for evt in event['events'])
            if not actual:
                changed.append({'task_id':flat['task_id'],'condition':flat['condition'],
                                'fault':flat['fault'],'old_injected_fault':flat['injected_fault'],
                                'old_recovered':flat['injected_fault_recovered'],
                                'new_injected_fault':0,'new_recovered':0,
                                'reason':'No transport_injection event in saved log'})
                flat['injected_fault']='0'
                flat['injected_fault_recovered']='0'
                event['injected_fault']=0
                event['injected_fault_recovered']=0
    corrected=DEST/'corrected_baselines'
    write_csv(corrected/'trials.csv',original,fields)
    with (corrected/'attempt_events.jsonl').open('w', encoding='utf-8') as fh:
        for row in detailed:
            fh.write(json.dumps(row,ensure_ascii=False)+'\n')
    shutil.copyfile(BASE/'manifest.json',corrected/'manifest.json')
    shutil.copyfile(BASE/'preinjection_failure_frequency.csv',corrected/'preinjection_failure_frequency.csv')
    groups=defaultdict(list)
    for r in original:
        groups[(r['condition'],r['fault'],r['feedback_format'],int(r['retry_budget']))].append(r)
    summary=[]
    for key, group in sorted(groups.items()):
        injected=[r for r in group if r['injected_fault']=='1']
        tokens=[int(r['total_tokens']) for r in group if r['total_tokens'].strip()]
        proposals=sum(int(r['model_proposals']) for r in group)
        summary.append({'condition':key[0], 'fault':key[1], 'feedback_format':key[2], 'retry_budget':key[3],
                        'n':len(group),
                        'completion_rate':sum(int(r['task_completed']) for r in group)/len(group),
                        'recovery_rate':sum(int(r['injected_fault_recovered']) for r in injected)/len(injected) if injected else 'N/A',
                        'mean_latency_seconds':statistics.mean(float(r['latency_seconds']) for r in group),
                        'mean_retries':statistics.mean(int(r['retry_count']) for r in group),
                        'mean_tokens':statistics.mean(tokens) if len(tokens)==len(group) else 'N/A',
                        'preinjection_error_rate':sum(int(r['spontaneous_preinjection_errors']) for r in group)/proposals if proposals else 'N/A',
                        'circuit_breaker_rate':sum(int(r['circuit_breaker_open']) for r in group)/len(group)})
    write_csv(corrected/'summary.csv',summary)
    write_csv(DEST/'fault_flag_corrections.csv',changed,
              ['task_id','condition','fault','old_injected_fault','old_recovered',
               'new_injected_fault','new_recovered','reason'])
    exposure=[]
    for (condition,fault),group in sorted(_groupby(original,('condition','fault')).items()):
        if fault=='none':
            continue
        observed=sum(int(r['injected_fault']) for r in group)
        exposure.append({'condition':condition,'fault':fault,'scheduled_fault_cells':len(group),
                         'realised_injected_cells':observed,
                         'realised_exposure_rate':round(observed/len(group),6)})
    write_csv(DEST/'scheduled_vs_realised_fault_exposure.csv',exposure)
    print(f'BASELINE DATA: {len(original)} records copied; {len(changed)} false injection/recovery flag(s) corrected in NEW audit copy')
    for c in ('no_verification','naive_retry','closed_loop'):
        subset=[r for r in exposure if r['condition']==c]
        print(f'  {c}: realised {sum(x["realised_injected_cells"] for x in subset)}/scheduled {sum(x["scheduled_fault_cells"] for x in subset)}')
    return changed


def _groupby(records, keys):
    result=defaultdict(list)
    for r in records:
        result[tuple(r[k] for k in keys)].append(r)
    return result


def analyse_retry_matched():
    rows,_=csv_rows(RETRY/'trials.csv')
    bykey=_groupby([r for r in rows if r['condition']!='no_verification'],
                   ('condition','fault','retry_budget'))
    output=[]
    for (c,f,b),vals in sorted(bykey.items()):
        if len(vals)!=2:
            raise RuntimeError(f'Retry budget comparison missing expected 2 tasks: {c}/{f}/{b}: n={len(vals)}')
        budgetzero=bykey.get((c,f,'0'))
        if not budgetzero:
            raise RuntimeError(f'No zero-retry comparison for {c}/{f}')
        rate=statistics.mean(int(r['task_completed']) for r in vals)
        tokens=statistics.mean(int(r['total_tokens']) for r in vals)
        zerorate=statistics.mean(int(r['task_completed']) for r in budgetzero)
        zerotokens=statistics.mean(int(r['total_tokens']) for r in budgetzero)
        output.append({'condition':c, 'fault':f,'retry_budget':b,'n':len(vals),
                       'completion_rate':rate, 'mean_tokens':tokens,
                       'completion_rate_change_vs_budget_0':round(rate-zerorate,6),
                       'mean_token_change_vs_budget_0':round(tokens-zerotokens,3),
                       'observed_no_gain_with_higher_tokens':int(int(b)>0 and rate<=zerorate and tokens>zerotokens)})
    write_csv(DEST/'RQ3_retry_budget_matched_descriptive.csv',output)
    print(f'RQ3: {len(output)} matched condition/fault/budget cells summarised from {len(rows)} original retry records')
    return output


def update_hashes():
    source=ROOT/'PACKAGE_FILE_HASHES.json'
    recorded=json.loads(source.read_text(encoding='utf-8'))
    changed=[]
    for rel, prior in recorded.get('files',{}).items():
        p=ROOT/rel
        if p.exists():
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            if digest != prior:
                changed.append(rel)
            recorded['files'][rel]=digest
    (DEST/'PACKAGE_FILE_HASHES_VERIFIED.json').write_text(json.dumps(recorded,indent=2)+'\n',encoding='utf-8')
    print('SOURCE CHECKSUMS: new verified copy written; updated hashes for', ', '.join(changed) or 'none')


def report(changed):
    text=(
      'MCP thesis post-audit reconciliation (OFFLINE; no LLM rerun)\n'
      'Original result folders were not modified.\n\n'
      '1. Fault-injection correction: ' + str(len(changed)) + ' record(s) corrected in audit_verification/corrected_baselines.\n'
      '   Retain original results_ollama_baselines for provenance.\n'
      '2. scheduled_vs_realised_fault_exposure.csv compares planned and actual injections across policies.\n'
      '   Rates are not equal across conditions; do not report them as equal actual fault exposure.\n'
      '3. RQ3_retry_budget_matched_descriptive.csv compares budgets within each policy/fault using two tasks.\n'
      '   This descriptive sample is too small to establish a universal optimum or causal break-even point.\n'
      '4. RQ1 spontaneous errors reflect selected SYNTHETIC tasks, not production MCP prevalence.\n'
      '5. The retry-budget manifest planned 240 but only 237 were saved; all unique policy configurations were covered.\n'
      '6. PACKAGE_FILE_HASHES_VERIFIED.json contains final source hashes and does not overwrite the original file.\n'
      '7. Verify HTTP response payload using: python MCP_Audit_Corrections.py --http while server is running.\n'
      '8. The recovery-logging rule in experiment.py was corrected for FUTURE trials; do not rerun past trials.\n'
      '9. Public publication/open licence cannot be inferred from local code alone.\n'
    )
    (DEST/'AUDIT_NOTES.txt').write_text(text,encoding='utf-8')


async def http_value_check():
    from mcp import Client
    from verification import unwrap_mcp_reply
    async with Client('http://127.0.0.1:8000/mcp') as client:
        tools=[t.name for t in (await client.list_tools()).tools]
        if 'check_stock' not in tools:
            raise RuntimeError('check_stock was not offered by the MCP server')
        result=await client.call_tool('check_stock',{'sku':'PEN'})
        decoded,error=unwrap_mcp_reply(result)
        print('HTTP raw structured_content:',repr(getattr(result,'structured_content',None)))
        print('HTTP decoded stock payload:',repr(decoded))
        if error:
            raise RuntimeError('HTTP tool returned error: '+error.message)
        if not isinstance(decoded,dict) or decoded.get('sku')!='PEN' or decoded.get('available')!=30:
            raise RuntimeError('Stock content differs from expected synthetic PEN=30; inspect displayed payload')
        print('HTTP STOCK VALUE: PASS')


def main():
    parser=argparse.ArgumentParser(description='MCP thesis post-audit correction without rerunning experiments')
    parser.add_argument('--http',action='store_true',help='Validate HTTP stock-value decoding while server runs')
    args=parser.parse_args()
    if args.http:
        asyncio.run(http_value_check())
        return
    for p in (ROOT/'experiment.py',BASE/'trials.csv',BASE/'attempt_events.jsonl',RETRY/'trials.csv'):
        if not p.exists():
            raise FileNotFoundError(f'Required source/data file not found: {p}')
    DEST.mkdir(exist_ok=True)
    # Reconcile old data BEFORE patching the source; all outputs are separate.
    changed=reconcile_baseline()
    analyse_retry_matched()
    patch_logging()
    update_hashes()
    report(changed)
    print('OFFLINE CORRECTIONS: COMPLETE')
    print('Review:', DEST/'AUDIT_NOTES.txt')


if __name__=='__main__':
    main()
