# MCP thesis: final evidence from completed runs

Created from existing experiment files only. No AI calls, no new trials, no overwrites.

## Evidence integrity
- 4 completed datasets checked: 849 genuine Ollama trials (480 + 72 + 237 + 60).
- Corrected baseline used for analysis; original baseline remains untouched.
- 25 source-file hashes matched the previously verified manifest.
- The retry run has 237 saved rows (240 scheduled; no-verification repeat settings were skipped). Do not invent 3 rows.

## RQ1: failure frequency in controlled local conditions
- 1306 model-generated proposals were logged in the inventory baseline.
- malformed_payload: 390 observations (29.9% per proposal).
- parameter_type_mismatch: 0 observations (0.0% per proposal).
- schema_mismatch: 0 observations (0.0% per proposal).
- transient_api: 0 observations (0.0% per proposal).
- incorrect_tool: 43 observations (3.3% per proposal).
- semantic_failure: 0 observations (0.0% per proposal).
- safety_violation: 0 observations (0.0% per proposal).
- These are observed proposal errors in synthetic local task workflows, not measurements of external production MCP traffic.

## RQ2: performance with identical scheduled task/fault assignments
- no_verification: 9/160 complete (5.6%); 50/140 actually injected; mean tokens 877.3.
- naive_retry: 30/160 complete (18.8%); 57/140 actually injected; mean tokens 983.8.
- closed_loop: 131/160 complete (81.9%); 139/140 actually injected; mean tokens 4504.8.
The proposed comparison has equal *scheduled* fault rates, but early natural errors can prevent actual fault delivery.
A sensitivity check restricts attention to 50 matched task/fault cells where all three policies actually encountered an injection.
- matched no_verification: 0/50 complete (0.0%).
- matched naive_retry: 21/50 complete (42.0%).
- matched closed_loop: 39/50 complete (78.0%).
Post-hoc subset results are descriptive, not a new randomized experiment; selection can introduce bias.

## RQ3: completion, token cost and retry-policy budget
- closed-loop budget 0: 0/16 complete, mean tokens 879.2, mean latency 8.7s.
- closed-loop budget 1: 11/16 complete, mean tokens 4209.2, mean latency 44.2s.
- closed-loop budget 2: 13/16 complete, mean tokens 5044.5, mean latency 50.9s.
- closed-loop budget 3: 15/16 complete, mean tokens 5027.0, mean latency 50.9s.
- closed-loop budget 4: 16/16 complete, mean tokens 5221.1, mean latency 53.6s.
- Within the tested budgets (0–4) the closed-loop success rate kept improving. No universal break-even threshold was observed. Claims beyond the measured range would be unsupported.
- Cost is model-reported token count, not dollars. No monetary costs were measured.

## RQ4: three feedback formats
- raw_trace: 22/24 complete (91.7%); mean tokens 3458.5.
- schema_diff: 20/24 complete (83.3%); mean tokens 4197.3.
- natural_language: 15/24 complete (62.5%); mean tokens 3901.0.
Comparison is based on three tasks per failure scenario; do not claim population-wide superiority.

## BFCL benchmark
- no_verification: 9/20 correct.
- naive_retry: 8/20 correct.
- closed_loop: 8/20 correct.
BFCL is an adapted, independent 20-case single-call subset, not an official leaderboard submission.

## Deployment/publication status
- Local MCP HTTP transport and stock response passed on user Windows. Server shutdown with Ctrl+C was normal.
- Source code is packaged for public release. A public repository URL must be added only after the user publishes it.
- This is a faithful empirical accounting, not a claim of real-world fault prevalence or a universal cost optimum.
