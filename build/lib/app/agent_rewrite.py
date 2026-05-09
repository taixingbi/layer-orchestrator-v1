"""History formatting and third-person normalization (shared with intent router + RAG snippet)."""
import re
from typing import List, Tuple

CANDIDATE_NAME = "Taixing Bi"
HISTORY_CAP = 20
REWRITE_HISTORY_MAX_LINES = 6
ANSWER_HISTORY_MAX_LINES = 4


def rewrite_to_third_person(question: str) -> str:
    """Rewrite second-person references (you, your, etc.) to third person (candidate name)."""
    q = question
    # Order matters: longer/phrase patterns before "you" so e.g. "your" → "Taixing Bi's", "are you" → "is Taixing Bi"
    replacements = [
        (r"\byour\b", f"{CANDIDATE_NAME}'s"),
        (r"\byourself\b", CANDIDATE_NAME),
        (r"\bare you\b", f"is {CANDIDATE_NAME}"),
        (r"\bdo you\b", f"does {CANDIDATE_NAME}"),
        (r"\bhave you\b", f"has {CANDIDATE_NAME}"),
        (r"\bcan you\b", f"can {CANDIDATE_NAME}"),
        (r"\byou\b", CANDIDATE_NAME),
    ]
    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q, flags=re.IGNORECASE)
    return q


def normalize_history_turns(turns: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Strip contents and cap length (last HISTORY_CAP turns)."""
    out: List[Tuple[str, str]] = []
    for role, content in turns:
        r = (role or "").strip().lower()
        c = (content or "").strip()
        if r not in ("user", "assistant") or not c:
            continue
        out.append((r, c))
    return out[-HISTORY_CAP:]


def format_history_for_prompt(turns: List[Tuple[str, str]], max_turns: int) -> str:
    """Format turns as User:/Assistant: lines (last max_turns only)."""
    chunk = turns[-max_turns:] if max_turns > 0 else turns
    lines: List[str] = []
    for role, content in chunk:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def history_snippet_for_answer(
    history: List[Tuple[str, str]],
    current_question_raw: str,
    max_turns: int = ANSWER_HISTORY_MAX_LINES,
) -> str:
    """Short transcript for the final answer prompt (prior turns + current user message)."""
    if not history and not (current_question_raw or "").strip():
        return ""
    turns = list(history) + [("user", (current_question_raw or "").strip())]
    return format_history_for_prompt(turns, max_turns)
