"""Skill Mix mode's decomposition step — like Learning Path's decompose_topic,
but first identifies the distinct skill domains a composite topic spans
(e.g. "a good LinkedIn graphic post" needs both LinkedIn content strategy
and graphic design), then produces subtopics across them.

Subtopics come back domain-prefixed as plain strings (e.g. "Graphic Design:
choosing a template"), not as separate structured fields — this lets the
rest of the pipeline (subtopic_search, assembler, path_ranker, all built
for Learning Path) be reused completely unchanged; they only ever see
subtopic strings; the domain context rides along inside the string itself.

The LLM call itself is what does the "auto-detection": if a topic turns
out to be single-domain despite reaching this mode, it's free to return
just one domain and proceed normally rather than forcing an artificial
split.
"""
from llm_client import call_json


def _build_prompt(topic: str, level: str) -> str:
    level_hint = f' The learner\'s requested level is "{level}".' if level != "all" else ""
    return f"""You are designing a syllabus for a topic that may require combining
multiple DISTINCT SKILLS - fields normally taught by different kinds of
experts, where no single course or creator would plausibly cover both well.

A domain split is justified only when the skills are genuinely separate
fields. It is NOT justified for sub-areas within one coherent skill, even
if that skill has many facets.

Example A (one domain - do NOT split): "learn python" - variables, loops,
functions, file I/O, debugging are all facets of ONE skill (programming
fundamentals), normally taught together in a single well-structured course.
domains: ["Python programming"].

Example B (multiple domains - DO split): "a good LinkedIn graphic post"
genuinely needs LinkedIn content strategy AND graphic design - different
fields, different expert channels, no single course plausibly covers both.
domains: ["LinkedIn content strategy", "Graphic design"].

When in doubt, prefer ONE domain. A false split is worse than a missed one.

For the topic below, identify the domain(s) by this standard, then break it
into an ordered list of 6-10 subtopics covering all identified domains,
each written as "<Domain>: <specific subtopic>" (e.g. "Graphic Design:
choosing a template that matches your brand"). Keep each subtopic broad
enough to be its own YouTube search topic.{level_hint}

Topic: "{topic}"

Return ONLY valid JSON in this shape, no preamble:
{{
  "level": "beginner" | "intermediate" | "advanced",
  "domains": ["domain 1", "domain 2", ...],
  "subtopics": ["Domain 1: specific subtopic", "Domain 2: specific subtopic", ...]
}}"""


def decompose_skill_mix(topic: str, level: str = "all") -> dict:
    result = call_json(_build_prompt(topic, level), max_tokens=600)
    return {
        "level": result.get("level", "beginner"),
        "domains": result.get("domains", []),
        "subtopics": result.get("subtopics", []),
    }
