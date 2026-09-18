"""Step 1 — Topic Decomposition (instructions.md's Learning Path Feature).
One LLM call, ~500 tokens, breaks the topic into an ordered subtopic syllabus."""
from llm_client import call_json


def _build_prompt(topic: str, level: str) -> str:
    level_hint = f' The learner\'s requested level is "{level}".' if level != "all" else ""
    return f"""You are designing a syllabus for learning a topic from YouTube tutorials.
Break the topic below into an ordered list of 6-10 subtopics that together
give complete coverage, from first principles to practical application. Keep
each subtopic broad enough to be its own YouTube search topic — don't split
into more granular steps than that.{level_hint}

Topic: "{topic}"

Return ONLY valid JSON in this shape, no preamble:
{{
  "level": "beginner" | "intermediate" | "advanced",
  "subtopics": ["first subtopic", "second subtopic", ...]
}}"""


def decompose_topic(topic: str, level: str = "all") -> dict:
    result = call_json(_build_prompt(topic, level), max_tokens=500)
    return {
        "level": result.get("level", "beginner"),
        "subtopics": result.get("subtopics", []),
    }
