"""
Test the agent directly, without Telegram, using evals/questions.json.

Usage:
    AIPIPE_TOKEN=... python test_local.py
"""
import json
from agent import run_agent

with open("evals/questions.json") as f:
    cases = json.load(f)

for i, case in enumerate(cases):
    print(f"\n=== Case {i} ===")
    print("Q:", case["messages"][-1][:120], "...")
    answer, log_url = run_agent(case["messages"])
    print("Answer:", answer)
    print("Log URL:", log_url or "(no GITHUB_TOKEN set, skipped)")
