from typing import Dict, Set


VALID_STATES = {"PENDING", "PROCESSING", "COMPLETED", "FAILED"}


ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "PENDING":    {"PROCESSING", "FAILED"},
    "PROCESSING": {"COMPLETED", "FAILED"},
    "COMPLETED":  set(),
    "FAILED":     set(),
}


class InvalidTransitionError(Exception):
    """Raised when a payment tries to move to a status that is not allowed."""
    pass


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status not in VALID_STATES:
        return False
    if to_status not in VALID_STATES:
        return False
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise InvalidTransitionError(
            "Invalid transition: " + from_status + " -> " + to_status
        )
