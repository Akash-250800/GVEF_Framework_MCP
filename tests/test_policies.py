import pytest
pytest.importorskip("mcp")
from agents import ScriptedDiagnosticAgent
from benchmarks import inventory_tasks
from experiment import run_trial, configs
from taxonomy import FAULTS,CONDITIONS,FEEDBACKS


def test_full_experiment_matrix_has_all_factors():
    rows=configs("all",CONDITIONS,FAULTS,FEEDBACKS,(2,0,1,3))
    assert any(x[0]=="no_verification" for x in rows)
    assert any(x[0]=="naive_retry" for x in rows)
    assert any(x[0]=="closed_loop" for x in rows)
    assert all(any(x[1]==f for x in rows) for f in FAULTS)
    assert all(any(x[2]==style for x in rows) for style in FEEDBACKS)
    assert all(any(x[3]==budget for x in rows) for budget in (0,1,2,3))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault",FAULTS)
@pytest.mark.parametrize("condition",CONDITIONS)
async def test_three_policies_across_faults(fault, condition):
    task=inventory_tasks()[0]
    row=await run_trial(ScriptedDiagnosticAgent(), task, condition,fault,"schema_diff",2)
    if fault=="none":
        expected=True
    elif fault in ("transient_api","transient_timeout","transient_rate_limit"):
        expected=(condition!="no_verification")
    else:
        expected=(condition=="closed_loop")
    assert bool(row["task_completed"])==expected, (condition,fault,row["last_error"])
    assert row["total_tokens"] is None
    assert not row["token_measurement_complete"]


@pytest.mark.asyncio
async def test_feedback_and_retry_ablation():
    task=inventory_tasks()[0]
    for style in FEEDBACKS:
        row=await run_trial(ScriptedDiagnosticAgent(),task,"closed_loop","stale_schema",style,2)
        assert row["task_completed"]==1
        assert row["injected_fault_recovered"]==1
    no_retries=await run_trial(ScriptedDiagnosticAgent(),task,"closed_loop","stale_schema","schema_diff",0)
    assert no_retries["task_completed"]==0
    assert no_retries["circuit_breaker_open"]==1
