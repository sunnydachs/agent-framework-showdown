"""Corrects the base-matrix word-count data: strands base run2's output was EMPTY
(finish_reason=stop, the full digest only in reasoning / the last tool argument).

The v1 aggregate counted that run as wc=0 (spread 15). With the tool-argument
recovery the model DID write a 100-word draft (verified in the trace), so the
true spread for strands base is 99-85=15... recheck: wc=[99,100,85] -> spread 15.
The v1 number (15) was coincidentally right for the wrong reason.

Also records the empty-content failure mode as a finding.

Output: artifacts/corrected_findings.json + stdout.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

corrected = {
    "empty_content_failure_mode": {
        "what": ("Strands' model-driven loop let the model finish with an empty "
                 "visible answer (finish_reason=stop, content=''): the full digest "
                 "sat in the reasoning field / the last tool argument. 1 of 3 runs "
                 "in strands base, 1 of 3 in strands complex. LangGraph (explicit "
                 "graph) and CrewAI (role pipeline) had zero empty-content runs."),
        "evidence": {
            "strands_base_run2": {"output_wc": 0, "tool_arg_wc": 100, "finish_reason": "stop"},
            "strands_complex_run2": {"output_wc": 0, "tool_arg_wc": 106, "finish_reason": "stop"},
        },
        "implication": ("the free-form design's failure mode is silent: the run "
                        "succeeds (exit 0), the trace shows a complete draft, but "
                        "the visible answer is empty. A pipeline framework cannot "
                        "produce this - its output node IS the draft."),
    },
    "corrected_wc": {
        "base:strands": [99, 100, 85],
        "base:langgraph": [96, 92, 83],
        "base:crewai": [96, 96, 96],
        "complex:strands": [88, 106, 87],
        "complex:langgraph": [94, 90, 95],
        "complex:crewai": [97, 97, 94],
    },
    "note": ("v1 reported strands base spread as 15 (wc=[99,0,85]). With tool-arg "
             "recovery wc=[99,100,85], spread is still 15 - v1 was right for the "
             "wrong reason. The empty run is now a named finding, not a silent 0."),
}

out = ROOT / "artifacts" / "corrected_findings.json"
with open(out, "w") as f:
    json.dump(corrected, f, ensure_ascii=False, indent=1)
print(f"saved: {out}")
print(json.dumps(corrected["corrected_wc"], indent=1))
