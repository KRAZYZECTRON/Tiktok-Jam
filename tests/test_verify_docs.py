"""Tests for the documentation-drift scanner in tools/verify_claims.py.

These exist because the scanner shipped broken. Its first version compared
superseded literals against the raw markdown line, so `MRR **0.9438**` — the
exact form the stale figure actually took in TASKS.md — slipped straight
through while `score 0.9522` was caught. The gap was found by deliberately
injecting both figures and noticing only one was reported.

A drift check that cannot itself fail is worse than no check, because it is
quoted as evidence. So the emphasis-stripping behaviour is pinned here.
"""
from __future__ import annotations

import pathlib

import pytest

from tools.verify_claims import DOC_SCAN_SKIP, SUPERSEDED, superseded_hits

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_plain_superseded_literal_is_caught():
    hits = superseded_hits("TASKS.md", "main - score 0.9522 today\n")
    assert len(hits) == 1
    assert "score 0.9522" in hits[0]
    assert hits[0].startswith("TASKS.md:1:")


@pytest.mark.parametrize(
    "line",
    [
        "MRR **0.9438**",           # bold, the form that escaped the first version
        "MRR *0.9438*",             # italic
        "MRR `0.9438`",             # code span
        "**MRR 0.9438**",           # whole phrase bolded
        "MRR ***0.9438***",         # bold italic
    ],
)
def test_markdown_emphasis_does_not_hide_a_stale_figure(line):
    assert superseded_hits("TASKS.md", line), f"emphasis hid the literal: {line!r}"


def test_current_figures_are_not_flagged():
    current = (
        "`main` - Hit@10 **1.0000** - MRR **0.9465** - MTTC **2.545** "
        "- **score 0.953064**\n"
    )
    assert superseded_hits("TASKS.md", current) == []


def test_scoreboard_may_keep_its_history():
    """SCOREBOARD records superseded rows on purpose; flagging them is wrong."""
    historical = "| 29 Aug | rating tie-break | 1.0000 | 0.9438 | 2.55 | 0.9522 |\n"
    assert superseded_hits("SCOREBOARD.md", "MRR 0.9438 / score 0.9522\n") == []
    assert superseded_hits("SCOREBOARD.md", historical) == []
    # ...but a file with no exemption is still scanned.
    assert superseded_hits("README.md", "MRR 0.9438\n")


def test_dated_log_is_never_scanned():
    """Rewriting what a past log entry measured would be falsifying it."""
    assert "OVERNIGHT_LOG.md" in DOC_SCAN_SKIP
    assert superseded_hits("OVERNIGHT_LOG.md", "80 tests pass, score 0.9522\n") == []


def test_line_numbers_are_reported_accurately():
    text = "alpha\nbeta\nMRR 0.9438\ndelta\n"
    (hit,) = superseded_hits("README.md", text)
    assert hit.startswith("README.md:3:")


def test_every_superseded_entry_is_wellformed():
    for literal, why, exempt in SUPERSEDED:
        assert literal and isinstance(literal, str)
        assert why, f"{literal!r} has no explanation; a bare failure is unactionable"
        assert isinstance(exempt, tuple)


def test_the_repository_itself_is_currently_clean():
    """The live guarantee, not a synthetic one."""
    failures = []
    for path in sorted(REPO.glob("*.md")):
        failures.extend(superseded_hits(path.name, path.read_text(encoding="utf-8")))
    assert not failures, "superseded figures presented as current:\n" + "\n".join(failures)
