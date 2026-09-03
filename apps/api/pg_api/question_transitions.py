from __future__ import annotations

from dataclasses import dataclass

from pg_domain import QuestionState


@dataclass(frozen=True, slots=True)
class QuestionTransition:
    source: str
    target: str
    active: bool
    increment_returned_count: bool = False


_ALLOWED: dict[str, frozenset[str]] = {
    QuestionState.CAPTURED.value: frozenset({
        QuestionState.EXPLORING.value,
        QuestionState.PAUSED.value,
        QuestionState.RETURNED.value,
        QuestionState.ACTIVE_TOPIC.value,
        QuestionState.CLOSED.value,
    }),
    QuestionState.EXPLORING.value: frozenset({
        QuestionState.PAUSED.value,
        QuestionState.RETURNED.value,
        QuestionState.ACTIVE_TOPIC.value,
        QuestionState.CLOSED.value,
    }),
    QuestionState.PAUSED.value: frozenset({
        QuestionState.RETURNED.value,
        QuestionState.EXPLORING.value,
        QuestionState.CLOSED.value,
    }),
    QuestionState.RETURNED.value: frozenset({
        QuestionState.EXPLORING.value,
        QuestionState.PAUSED.value,
        QuestionState.ACTIVE_TOPIC.value,
        QuestionState.CLOSED.value,
    }),
    QuestionState.ACTIVE_TOPIC.value: frozenset({
        QuestionState.PAUSED.value,
        QuestionState.RETURNED.value,
        QuestionState.CLOSED.value,
    }),
    QuestionState.CLOSED.value: frozenset(),
}


class InvalidQuestionTransition(ValueError):
    pass


class QuestionTransitionService:
    """The only service allowed to change a Question's lifecycle state."""

    @staticmethod
    def validate(state: str, target: str, returned_count: int) -> QuestionTransition:
        if target not in _ALLOWED:
            raise InvalidQuestionTransition(f"unknown question state: {target}")
        if target not in _ALLOWED.get(state, frozenset()):
            raise InvalidQuestionTransition(f"invalid question transition: {state} -> {target}")
        increment = target == QuestionState.RETURNED.value
        if increment and returned_count < 0:
            raise InvalidQuestionTransition("returned_count cannot be negative")
        return QuestionTransition(
            source=state,
            target=target,
            active=target not in {QuestionState.PAUSED.value, QuestionState.CLOSED.value},
            increment_returned_count=increment,
        )

    @classmethod
    def transition(cls, row, target: str) -> QuestionTransition:
        transition = cls.validate(row.state, target, row.returned_count)
        row.state = transition.target
        row.active = transition.active
        if transition.increment_returned_count:
            row.returned_count += 1
        return transition
