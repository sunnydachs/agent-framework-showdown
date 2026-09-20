"""Shared task definition: the SAME tools and the SAME goal for all 3 frameworks.

Task: "tech news digest" agent.
  - fetch_headlines(topic, count)  -> list of fake headlines (deterministic, no network)
  - word_count(text)               -> exact character/word count
The agent must collect headlines about a topic, then write a digest of about
100 words, and must verify the word count with the word_count tool.
"""
