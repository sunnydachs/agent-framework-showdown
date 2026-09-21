"""Shared structured-output tools for the F experiment (imported identically).

The F task: the digest must be returned as STRICT JSON matching a schema:
  {"summary": <100-word digest>, "word_count": <int>, "topics": [<strings>],
   "publish_ready": <bool>}

The schema is enforced three ways (the experiment):
  - strands: tool-based self-check + prompt instruction
  - langgraph: output-format prompt instruction (single call)
  - crewai: expected_output prompt instruction (role pipeline)

Compliance is measured POST-RUN: parse the final output as JSON, check the
schema keys exist, the types match, and word_count is accurate.
"""
