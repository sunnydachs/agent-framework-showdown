"""Shared deterministic tools for all three frameworks (imported identically).

DRIFT variant: the word-count tool's parameter is renamed content -> text2
while task prompts still reference the OLD name. Tests how each framework's
model copes when the tool schema and the instructions disagree (spec drift).
"""
