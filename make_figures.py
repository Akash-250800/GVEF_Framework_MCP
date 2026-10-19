"""Generate only graphs from actually collected experiment CSVs; never invent values."""
import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def main(path):
    root=Path(path)
    df=pd.read_csv(root/"trials.csv")
    if df.empty:
        raise ValueError("No experiment data found")
    out=root/"figures";out.mkdir(parents=True,exist_ok=True)
    # RQ2: three policy task completion rates, including per-fault breakdown.
    baseline=df[(df.feedback_format=="not_applicable") | ((df.condition=="closed_loop") & (df.feedback_format=="schema_diff"))]
    main_budget=sorted(df.retry_budget.unique())[0]
    if 2 in df.retry_budget.values:
        main_budget=2
    baseline=baseline[(baseline.retry_budget==main_budget)|(baseline.condition=="no_verification")]
    grouped=baseline.groupby(["fault","condition"]).task_completed.mean().unstack()
    if not grouped.empty:
        grouped.plot(kind="bar",rot=30)
        plt.title("Task completion by failure and policy")
        plt.ylabel("Completion rate");plt.ylim(0,1);plt.tight_layout()
        plt.savefig(out/"completion_by_fault.png",dpi=180);plt.close()
    # RQ3: completion vs tokens; only actual live-model measured tokens included.
    measured=df[(df.total_tokens.notna())&(df.token_measurement_complete==1)]
    if not measured.empty:
        summary=measured.groupby(["condition","feedback_format"]).agg(tokens=("total_tokens","mean"), success=("task_completed","mean")).reset_index()
        for _,row in summary.iterrows():
            plt.scatter(row.tokens,row.success)
            plt.annotate(f"{row.condition}/{row.feedback_format}",(row.tokens,row.success),fontsize=7)
        plt.xlabel("Mean model tokens per task");plt.ylabel("Completion rate")
        plt.ylim(0,1);plt.tight_layout();plt.savefig(out/"completion_vs_token_cost.png",dpi=180);plt.close()
    # RQ4: impact of feedback formats
    fb=df[(df.condition=="closed_loop")].groupby(["feedback_format","fault"]).task_completed.mean().unstack()
    if not fb.empty:
        fb.plot(kind="bar",rot=15);plt.ylabel("Completion rate");plt.ylim(0,1)
        plt.title("Feedback-format comparison");plt.tight_layout()
        plt.savefig(out/"feedback_comparison.png",dpi=180);plt.close()
    # Retry/circuit-breaker ablation
    retry=df.groupby(["retry_budget","condition"]).task_completed.mean().unstack()
    if not retry.empty:
        retry.plot(marker="o");plt.xlabel("Additional retries allowed");plt.ylabel("Completion rate")
        plt.ylim(0,1);plt.title("Retry-budget ablation");plt.tight_layout()
        plt.savefig(out/"retry_budget_ablation.png",dpi=180);plt.close()
    # Latency distribution, across all trial cells
    df.boxplot(column="latency_seconds",by="condition",rot=15)
    plt.suptitle("");plt.title("Elapsed time per task")
    plt.ylabel("Seconds");plt.tight_layout()
    plt.savefig(out/"latency_by_condition.png",dpi=180);plt.close()
    print(f"Figures saved to {out.resolve()}")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--results",default="results")
    x=p.parse_args()
    main(x.results)
