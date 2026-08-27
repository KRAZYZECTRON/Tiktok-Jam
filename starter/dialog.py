"""Seat 3: slot accumulation, intent override, 10-turn budget, clarification triggers.

The baseline tracked no cross-turn state at all -- every turn re-queried
retrieve() from scratch off the raw message text, ignoring turn number and
prior messages. This starts as a minimal accumulator (message + turn history)
for Seat 3 to build the real slot/override/clarification logic on top of.
"""
from __future__ import annotations

from .state import DialogState


def update_state(state: DialogState, message: str, turn: int) -> DialogState:
    state.turn = turn
    state.messages.append(message)
    return state
