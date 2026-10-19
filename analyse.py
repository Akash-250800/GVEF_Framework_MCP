"""Full research analysis of already-measured trials (no fabricated data)."""
import argparse
from pathlib import Path
import pandas as pd


def main(results):
    root=Path(results)
    df=pd.read_csv(root/"trials.csv")
    if df.empty:
        raise RuntimeError("No trial data found")
    destination=root/"analysis"
    destination.mkdir(parents=True,exist_ok=True)
    # RQ1: spontaneous pre-injection failure incidence was logged in the runner.
    # RQ2: matched baselines and reliability. Each run/replicate included as counted.
    base=df[(df.feedback_format.isin(["schema_diff","not_applicable"]))]
    base=(base.groupby(["condition","fault","retry_budget"],dropna=False)
          .agg(n=("task_completed","size"),completion_rate=("task_completed","mean"),
               recovery_rate=("injected_fault_recovered","mean"),
               mean_latency_seconds=("latency_seconds","mean"),
               mean_retries=("retry_count","mean")).reset_index())
    base.to_csv(destination/"RQ2_baseline_comparison.csv",index=False)
    # RQ3: cost/reliability tradeoffs and budget ablation.
    budget=(df.groupby(["condition","retry_budget","fault"],dropna=False)
            .agg(n=("task_completed","size"),completion_rate=("task_completed","mean"),
                 mean_retries=("retry_count","mean"),
                 mean_latency_seconds=("latency_seconds","mean"),
                 mean_tokens=("total_tokens","mean")).reset_index())
    budget.to_csv(destination/"RQ3_retry_budget_ablation.csv",index=False)
    cost=(df.groupby(["condition","fault","feedback_format","retry_budget"],dropna=False)
          .agg(n=("task_completed","size"),completion_rate=("task_completed","mean"),
               mean_tokens=("total_tokens","mean"),
               mean_latency_seconds=("latency_seconds","mean")).reset_index())
    cost.to_csv(destination/"RQ3_completion_cost_tradeoff.csv",index=False)
    # A higher cost with no improvement is dominated; do not assume specific ROI weights.
    frontier=[]
    available=cost[cost.mean_tokens.notna()]
    for _,r in available.iterrows():
        dominated=any((p.mean_tokens<=r.mean_tokens and p.completion_rate>=r.completion_rate and
                       (p.mean_tokens<r.mean_tokens or p.completion_rate>r.completion_rate))
                      for _,p in available.iterrows())
        if not dominated:
            frontier.append(r.to_dict())
    pd.DataFrame(frontier,columns=list(cost.columns)).to_csv(destination/"RQ3_pareto_frontier.csv",index=False)
    # RQ4: feedback-format comparisons within closed-loop trials only.
    feedback=df[df.condition=="closed_loop"]
    comparative=(feedback.groupby(["feedback_format","fault","retry_budget"],dropna=False)
                 .agg(n=("task_completed","size"),completion_rate=("task_completed","mean"),
                      recovery_rate=("injected_fault_recovered","mean"),
                      mean_tokens=("total_tokens","mean"),
                      mean_latency_seconds=("latency_seconds","mean")).reset_index())
    comparative.to_csv(destination/"RQ4_feedback_formats.csv",index=False)
    if df["mode"].eq("diagnostic").any():
        (destination/"NOT_LLM_EVIDENCE.txt").write_text(
            "This dataset contains scripted diagnostic trials. They are NOT empirical evidence of LLM performance.\n",
            encoding="utf-8")
    print("Research analysis files written to",destination.resolve())

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Analyse measured MCP experiments")
    parser.add_argument("--results",default="results")
    args=parser.parse_args()
    main(args.results)
