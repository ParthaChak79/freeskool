"""Step 4 — Path Assembly (instructions.md's Learning Path Feature).
One LLM call (~1000 tokens) generates the one-line "why" rationale per step.
Ordering and factual fields (title/channel/url/duration) come from the
deterministic assembler, not the LLM — avoids the model inventing URLs.
"""
from llm_client import call_json


def _build_prompt(topic: str, chosen_steps: list[dict]) -> str:
    lines = []
    for i, step in enumerate(chosen_steps, start=1):
        c = step["candidate"]
        subtopics = ", ".join(step["subtopics"])
        lines.append(
            f'Step {i}: subtopic(s)="{subtopics}", type={c["type"]}, '
            f'title="{c.get("title", "")}", channel="{c.get("channel_name", "")}", '
            f'summary="{c.get("summary", "")}"'
        )
    steps_text = "\n".join(lines)
    return f"""You are assembling a YouTube learning path for the topic "{topic}".
Below is the ordered sequence of steps already chosen for this path. For each
step, write a one-line rationale explaining what it adds and why it comes at
this point in the sequence.

{steps_text}

Return ONLY valid JSON, no preamble, in this shape:
[{{"step": 1, "why": "..."}}, {{"step": 2, "why": "..."}}, ...]"""


def generate_rationale(topic: str, chosen_steps: list[dict]) -> list[str]:
    if not chosen_steps:
        return []
    result = call_json(_build_prompt(topic, chosen_steps), max_tokens=1000)
    by_step = {r["step"]: r.get("why", "") for r in result}
    return [by_step.get(i, "") for i in range(1, len(chosen_steps) + 1)]
