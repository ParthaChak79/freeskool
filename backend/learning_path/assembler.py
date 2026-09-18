"""Step 3 — Dedup & Gap Filling (instructions.md's Learning Path Feature).
Deterministic — no LLM call. Walks the syllabus in order and, per subtopic:
  - if the best-scoring candidate was already selected for an earlier
    subtopic, that step already covers this one too (dedup, no redundant entry)
  - if the best candidate scores below GAP_SCORE_THRESHOLD, flag a gap
    instead of padding the path with a weak result
  - prefers a candidate sharing the previous step's channel when scores are
    within 0.3 of each other (continuity of teaching style)
"""
import config

CHANNEL_TIE_MARGIN = 0.3


def assemble_path(subtopics: list[str], ranked_candidates: list[dict], ids_by_subtopic: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    ranked_by_id = {c["_id"]: c for c in ranked_candidates}
    chosen_steps: list[dict] = []
    covered_ids: set[str] = set()
    gaps: list[str] = []

    for subtopic in subtopics:
        candidates = [ranked_by_id[cid] for cid in ids_by_subtopic.get(subtopic, []) if cid in ranked_by_id]
        candidates.sort(key=lambda c: c["score"], reverse=True)

        already_selected = next((c for c in candidates if c["_id"] in covered_ids), None)
        if already_selected:
            for step in chosen_steps:
                if step["candidate"]["_id"] == already_selected["_id"]:
                    step["subtopics"].append(subtopic)
                    break
            continue

        if not candidates or candidates[0]["score"] < config.GAP_SCORE_THRESHOLD:
            gaps.append(subtopic)
            continue

        best = candidates[0]
        if len(candidates) > 1 and chosen_steps:
            prev_channel = chosen_steps[-1]["candidate"].get("channel_name")
            for c in candidates:
                if abs(c["score"] - best["score"]) <= CHANNEL_TIE_MARGIN and c.get("channel_name") == prev_channel:
                    best = c
                    break

        covered_ids.add(best["_id"])
        chosen_steps.append({"subtopics": [subtopic], "candidate": best})

    return chosen_steps, gaps
