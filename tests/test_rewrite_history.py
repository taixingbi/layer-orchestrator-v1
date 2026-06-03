from app.core.rewrite import format_history_for_prompt


def test_format_history_truncates_per_turn_for_router():
    turns = [("user", "u" * 800), ("assistant", "a" * 600)]
    out = format_history_for_prompt(turns, 6, max_chars_per_turn=500)
    assert out.startswith("User: ")
    assert len(out.split("\n")[0]) == len("User: ") + 500
    assert out.split("\n")[0].endswith("…")
    assert "a" * 600 not in out


def test_format_history_no_truncation_by_default():
    text = "x" * 900
    out = format_history_for_prompt([("user", text)], 1)
    assert text in out
