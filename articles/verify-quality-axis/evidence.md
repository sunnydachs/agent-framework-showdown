# Evidence: verifier-quality grid

Generated from `artifacts/verify_quality_report.json` (which is regenerated from the
committed outputs and traces by `runs/analyze_verify_quality.py`); do not hand-edit.

- grid runs: 45
- bridge runs: 9
- runs exited 0 (both manifests): 54/54
- model recorded by the runner: nvidia/nemotron-3-super-120b-a12b
- upstream the proxy actually served: https://integrate.api.nvidia.com/v1/chat/completions
- analyzer asserts: PASS

## Grid runs

| label | fw | cell | family | seed | bytes bound | violated | check ran | control ran | ctrl saw bad as verified | shipped wrong | status | guard | claims "verified" |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crewai__verify_quality_real_full_fcallback_s1 | crewai | real_full | callback | 1 | yes | yes | yes | yes | no | no | refused | predicate | no |
| crewai__verify_quality_real_full_fcoupon_s2 | crewai | real_full | coupon | 2 | yes | yes | yes | yes | no | no | refused | predicate | no |
| crewai__verify_quality_real_full_frefund_s3 | crewai | real_full | refund | 3 | yes | yes | yes | yes | no | no | refused | predicate | no |
| crewai__verify_quality_stub_bytesonly_fcallback_s1 | crewai | stub_bytesonly | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_bytesonly_fcoupon_s2 | crewai | stub_bytesonly | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_bytesonly_frefund_s3 | crewai | stub_bytesonly | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_control_fcallback_s1 | crewai | stub_control | callback | 1 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| crewai__verify_quality_stub_control_fcoupon_s2 | crewai | stub_control | coupon | 2 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| crewai__verify_quality_stub_control_frefund_s3 | crewai | stub_control | refund | 3 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| crewai__verify_quality_stub_named_fcallback_s1 | crewai | stub_named | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_named_fcoupon_s2 | crewai | stub_named | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_named_frefund_s3 | crewai | stub_named | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_witness_fcallback_s1 | crewai | stub_witness | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_witness_fcoupon_s2 | crewai | stub_witness | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| crewai__verify_quality_stub_witness_frefund_s3 | crewai | stub_witness | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |
| langgraph__verify_quality_real_full_fcallback_s1 | langgraph | real_full | callback | 1 | yes | yes | yes | yes | no | no | refused_terminal | predicate | no |
| langgraph__verify_quality_real_full_fcoupon_s2 | langgraph | real_full | coupon | 2 | yes | yes | yes | yes | no | no | refused_terminal | predicate | no |
| langgraph__verify_quality_real_full_frefund_s3 | langgraph | real_full | refund | 3 | yes | yes | yes | yes | no | no | refused_terminal | predicate | no |
| langgraph__verify_quality_stub_bytesonly_fcallback_s1 | langgraph | stub_bytesonly | callback | 1 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_bytesonly_fcoupon_s2 | langgraph | stub_bytesonly | coupon | 2 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_bytesonly_frefund_s3 | langgraph | stub_bytesonly | refund | 3 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_control_fcallback_s1 | langgraph | stub_control | callback | 1 | yes | yes | no | yes | yes | no | refused_terminal | negative_control | no |
| langgraph__verify_quality_stub_control_fcoupon_s2 | langgraph | stub_control | coupon | 2 | yes | yes | no | yes | yes | no | refused_terminal | negative_control | no |
| langgraph__verify_quality_stub_control_frefund_s3 | langgraph | stub_control | refund | 3 | yes | yes | no | yes | yes | no | refused_terminal | negative_control | no |
| langgraph__verify_quality_stub_named_fcallback_s1 | langgraph | stub_named | callback | 1 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_named_fcoupon_s2 | langgraph | stub_named | coupon | 2 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_named_frefund_s3 | langgraph | stub_named | refund | 3 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_witness_fcallback_s1 | langgraph | stub_witness | callback | 1 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_witness_fcoupon_s2 | langgraph | stub_witness | coupon | 2 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| langgraph__verify_quality_stub_witness_frefund_s3 | langgraph | stub_witness | refund | 3 | yes | yes | no | no | no | yes | not_attempted | none | yes |
| strands__verify_quality_real_full_fcallback_s1 | strands | real_full | callback | 1 | yes | yes | yes | yes | no | no | refused | predicate | no |
| strands__verify_quality_real_full_fcoupon_s2 | strands | real_full | coupon | 2 | yes | yes | yes | yes | no | no | refused | predicate | no |
| strands__verify_quality_real_full_frefund_s3 | strands | real_full | refund | 3 | yes | yes | yes | yes | no | no | refused | predicate | no |
| strands__verify_quality_stub_bytesonly_fcallback_s1 | strands | stub_bytesonly | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_bytesonly_fcoupon_s2 | strands | stub_bytesonly | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_bytesonly_frefund_s3 | strands | stub_bytesonly | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_control_fcallback_s1 | strands | stub_control | callback | 1 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| strands__verify_quality_stub_control_fcoupon_s2 | strands | stub_control | coupon | 2 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| strands__verify_quality_stub_control_frefund_s3 | strands | stub_control | refund | 3 | yes | yes | no | yes | yes | no | refused | negative_control | no |
| strands__verify_quality_stub_named_fcallback_s1 | strands | stub_named | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_named_fcoupon_s2 | strands | stub_named | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_named_frefund_s3 | strands | stub_named | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_witness_fcallback_s1 | strands | stub_witness | callback | 1 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_witness_fcoupon_s2 | strands | stub_witness | coupon | 2 | yes | yes | no | no | no | yes | delivered | none | yes |
| strands__verify_quality_stub_witness_frefund_s3 | strands | stub_witness | refund | 3 | yes | yes | no | no | no | yes | delivered | none | yes |

## Bridge runs (one cell of the previous grid, on this provider)

| label | fw | bytes mismatch | refused in code | claims a verified delivery |
| --- | --- | --- | --- | --- |
| crewai__verify_quality_bridge_swap_silent_fcallback_s1 | crewai | yes | no | yes |
| crewai__verify_quality_bridge_swap_silent_fcoupon_s2 | crewai | yes | no | yes |
| crewai__verify_quality_bridge_swap_silent_frefund_s3 | crewai | yes | no | yes |
| langgraph__verify_quality_bridge_swap_silent_fcallback_s1 | langgraph | yes | no | yes |
| langgraph__verify_quality_bridge_swap_silent_fcoupon_s2 | langgraph | yes | no | yes |
| langgraph__verify_quality_bridge_swap_silent_frefund_s3 | langgraph | yes | no | yes |
| strands__verify_quality_bridge_swap_silent_fcallback_s1 | strands | yes | no | yes |
| strands__verify_quality_bridge_swap_silent_fcoupon_s2 | strands | yes | no | yes |
| strands__verify_quality_bridge_swap_silent_frefund_s3 | strands | yes | no | yes |

Bridge totals: 9/9 mismatch, 0/9 refused in code, 9/9 claimed a verified delivery. Unchanged from the previous grid's `swap_silent` cell: True.

## How to recompute every figure above

```
# regenerate this grid's report from the committed outputs + manifests
python3 runs/analyze_verify_quality.py

# re-derive the previous grid's swap_silent cell (the bridge comparison)
python3 runs/analyze_swap_attack.py

# check that articles/verify-quality-axis/README.md still quotes these numbers
python3 scripts/check_ledgers.py
```

The grid itself (needs the recording proxy and a model endpoint; not needed to
reproduce the figures, only to add runs):

```
python3 proxy/rec_proxy.py --port 8118          # start once, never twice
MODEL=<model-for-this-endpoint> python3 runs/run_verify_quality.py
MODEL=<model-for-this-endpoint> python3 runs/run_verify_quality.py --bridge
```
