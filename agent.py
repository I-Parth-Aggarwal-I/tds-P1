"""
LLM agent for the data-analyst Telegram bot.

Flow:
  1. Send the conversation + a `run_python` tool to the LLM via aipipe
     (OpenAI-compatible chat completions endpoint).
  2. If the model calls the tool, execute the code in a subprocess
     (pandas / numpy / requests available), feed the result back.
  3. Repeat until the model returns a final answer with no tool call.
  4. The model's final message must be exactly: {"answer": <...>}
     (it does NOT include log_url — the server fills that in after
     uploading the run log).
  5. Every step is appended to a JSONL trace and pushed to a public
     GitHub Gist; the raw gist URL is returned as log_url.
"""

import os
import json
import time
import uuid
import subprocess
import textwrap
import requests

AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]
AIPIPE_BASE_URL = os.environ.get("AIPIPE_BASE_URL", "https://aipipe.org/openai/v1")
AIPIPE_MODEL = os.environ.get("AIPIPE_MODEL", "gpt-4o-mini")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # for gist log upload

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a rigorous data analyst agent. You receive a short conversation
    from a user; the LAST message contains (or points to) a data-analysis
    question. Some questions embed data directly in the text; others point
    at a public dataset (e.g. MOSPI) that you must fetch yourself.

    You have one tool, `run_python`, which executes Python code with
    internet access and the libraries: pandas, numpy, requests,
    beautifulsoup4 (as bs4), io. Use it to fetch data, compute, and verify
    your answer before responding. Always print() the values you need to
    see — you only get stdout/stderr back, not variables.

    The user's message will specify the exact JSON shape the final answer
    must take (e.g. {"state": "..."}) or ask for a plain value. Once you
    are confident in the answer, reply with ONLY this JSON object and
    nothing else — no markdown fences, no explanation:

        {"answer": <the answer in the exact shape requested>}

    Do not include a log_url field yourself; it is added automatically.
    Verify arithmetic and data lookups with run_python rather than
    guessing — you will be graded on correctness.
""")

RUN_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Execute Python code and return its stdout/stderr. "
            "pandas, numpy, requests, and bs4 are pre-imported. "
            "Has internet access for fetching public datasets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to run"}
            },
            "required": ["code"],
        },
    },
}

MAX_TURNS = 8
EXEC_TIMEOUT_SECONDS = 45

_PRELUDE = (
    "import pandas as pd\n"
    "import numpy as np\n"
    "import requests\n"
    "from bs4 import BeautifulSoup\n"
    "import io, json, re\n"
)


def run_python(code: str) -> str:
    """Run user/model-generated data-analysis code in a subprocess sandbox."""
    full_code = _PRELUDE + "\n" + code
    try:
        result = subprocess.run(
            ["python3", "-c", full_code],
            capture_output=True,
            text=True,
            timeout=EXEC_TIMEOUT_SECONDS,
        )
        out = result.stdout[-4000:]
        err = result.stderr[-2000:]
        return json.dumps({"stdout": out, "stderr": err, "returncode": result.returncode})
    except subprocess.TimeoutExpired:
        return json.dumps({"stdout": "", "stderr": "TIMEOUT: execution exceeded 45s", "returncode": -1})


def _call_llm(messages):
    resp = requests.post(
        f"{AIPIPE_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {AIPIPE_TOKEN}"},
        json={
            "model": AIPIPE_MODEL,
            "messages": messages,
            "tools": [RUN_PYTHON_TOOL],
            "temperature": 0,
        },
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def _upload_log_to_gist(trace_lines: list[str], run_id: str) -> str:
    """Push the JSONL trace to a public GitHub Gist; return the raw URL."""
    content = "\n".join(trace_lines)
    if not GITHUB_TOKEN:
        # Fallback: no gist upload configured. Caller should still have a
        # local copy; this just means log_url will be empty.
        return ""
    resp = requests.post(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "description": f"agent run log {run_id}",
            "public": True,
            "files": {f"run-{run_id}.jsonl": {"content": content}},
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["files"][f"run-{run_id}.jsonl"]["raw_url"]


def run_agent(history: list[str]):
    """
    history: list of prior plain-text messages in this chat, last one is
    the question to answer.
    Returns: (answer_value, log_url)
    """
    run_id = uuid.uuid4().hex[:12]
    trace: list[str] = []

    def log_event(event: dict):
        event["ts"] = time.time()
        trace.append(json.dumps(event, ensure_ascii=False))

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for i, msg in enumerate(history):
        role = "user"
        messages.append({"role": role, "content": msg})

    log_event({"type": "run_start", "run_id": run_id, "history": history})

    final_answer = None
    for turn in range(MAX_TURNS):
        response = _call_llm(messages)
        choice = response["choices"][0]
        msg = choice["message"]
        log_event({"type": "llm_response", "turn": turn, "message": msg})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            messages.append(msg)
            for tc in tool_calls:
                if tc["function"]["name"] == "run_python":
                    args = json.loads(tc["function"]["arguments"])
                    code = args.get("code", "")
                    log_event({"type": "tool_call", "turn": turn, "code": code})
                    result = run_python(code)
                    log_event({"type": "tool_result", "turn": turn, "result": json.loads(result)})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
            continue

        # No tool call -> this should be the final answer.
        content = (msg.get("content") or "").strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(content)
            final_answer = parsed.get("answer", parsed)
        except json.JSONDecodeError:
            final_answer = content  # fall back to raw text if model didn't follow format
        log_event({"type": "final_answer", "turn": turn, "answer": final_answer})
        break

    if final_answer is None:
        final_answer = "ERROR: agent did not converge within MAX_TURNS"
        log_event({"type": "error", "message": final_answer})

    log_url = _upload_log_to_gist(trace, run_id)
    log_event({"type": "run_end", "log_url": log_url})

    return final_answer, log_url
