"""Shared Gemini call + retry + JSON-parsing, used by scorer/llm_scorer.py and
learning_path/decomposer.py + path_ranker.py — the same rate-limit/parsing
logic was getting duplicated across all three LLM call sites."""
import json
import time

import openai

import config

# See scorer/llm_scorer.py's note: this smooths cumulative multi-call bursts,
# not a single request that alone exceeds the account's per-minute quota.
MAX_RETRIES = 3
RETRY_BASE_DELAY_SEC = 5

_client = openai.OpenAI(api_key=config.GEMINI_API_KEY, base_url=config.GEMINI_BASE_URL)


def call_json(prompt: str, max_tokens: int) -> dict | list:
    attempt = 0
    while True:
        try:
            response = _client.chat.completions.create(
                model=config.GEMINI_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                # Gemini 3's hidden "thinking" tokens count against max_tokens
                # and left responses truncated to empty at this task's budgets
                # (confirmed live: finish_reason="length" with 0 visible
                # completion tokens). This is straightforward rubric-applying
                # JSON output, not a task that benefits from deep reasoning.
                reasoning_effort="minimal",
            )
            break
        except openai.APIStatusError as e:
            is_rate_limit = e.status_code in (429, 413)
            if not is_rate_limit or attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_BASE_DELAY_SEC * (2 ** attempt))
            attempt += 1

    return _parse_json(response.choices[0].message.content)


def _parse_json(text: str) -> dict | list:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("["), text.find("{")) if i != -1), default=-1)
        end = max(text.rfind("]"), text.rfind("}"))
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise
