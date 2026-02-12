"""
Provider State Machine

Defines allowed states and valid transitions for provider recruitment flow.
All states and transitions are derived from contracts/state_machine.json.
"""

from enum import Enum
from typing import Final

import structlog

from agents.shared.exceptions import InvalidStateTransitionError

log = structlog.get_logger()


class ProviderStatus(str, Enum):
    """
    Provider status enum.
    
    States are mutually exclusive and represent the current stage
    of a provider in the recruitment workflow.
    """
    
    INVITED = "INVITED"
    """Provider invited to campaign, initial outreach pending."""
    
    WAITING_RESPONSE = "WAITING_RESPONSE"
    """Outreach sent, awaiting provider reply."""
    
    WAITING_DOCUMENT = "WAITING_DOCUMENT"
    """Response received, required document(s) not yet submitted."""
    
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    """Document uploaded, Textract OCR in progress."""
    
    UNDER_REVIEW = "UNDER_REVIEW"
    """Automated screening complete, manual review needed."""
    
    QUALIFIED = "QUALIFIED"
    """Provider meets all requirements, approved for campaign."""
    
    REJECTED = "REJECTED"
    """Provider does not meet requirements or declined."""
    
    ESCALATED = "ESCALATED"
    """Edge case requiring human intervention."""
    
    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state (no outgoing transitions)."""
        return self in TERMINAL_STATES
    
    @classmethod
    def from_string(cls, value: str) -> "ProviderStatus":
        """Convert string to ProviderStatus enum."""
        try:
            return cls(value.upper())
        except ValueError as e:
            raise ValueError(
                f"Invalid provider status: '{value}'. "
                f"Valid values are: {[s.value for s in cls]}"
            ) from e


# Terminal states have no outgoing transitions
TERMINAL_STATES: Final[frozenset[ProviderStatus]] = frozenset({
    ProviderStatus.QUALIFIED,
    ProviderStatus.REJECTED,
})

# Valid state transitions map
# Key: current status, Value: set of allowed next statuses
VALID_TRANSITIONS: Final[dict[ProviderStatus, frozenset[ProviderStatus]]] = {
    ProviderStatus.INVITED: frozenset({
        ProviderStatus.WAITING_RESPONSE,
    }),
    ProviderStatus.WAITING_RESPONSE: frozenset({
        ProviderStatus.WAITING_DOCUMENT,
        ProviderStatus.DOCUMENT_PROCESSING,
        ProviderStatus.QUALIFIED,
        ProviderStatus.REJECTED,
        ProviderStatus.UNDER_REVIEW,
    }),
    ProviderStatus.WAITING_DOCUMENT: frozenset({
        ProviderStatus.DOCUMENT_PROCESSING,
        ProviderStatus.REJECTED,
        ProviderStatus.ESCALATED,
    }),
    ProviderStatus.DOCUMENT_PROCESSING: frozenset({
        ProviderStatus.UNDER_REVIEW,
        ProviderStatus.WAITING_DOCUMENT,
        ProviderStatus.QUALIFIED,
        ProviderStatus.REJECTED,
    }),
    ProviderStatus.UNDER_REVIEW: frozenset({
        ProviderStatus.QUALIFIED,
        ProviderStatus.REJECTED,
        ProviderStatus.ESCALATED,
    }),
    ProviderStatus.QUALIFIED: frozenset(),  # Terminal
    ProviderStatus.REJECTED: frozenset(),   # Terminal
    ProviderStatus.ESCALATED: frozenset({
        ProviderStatus.QUALIFIED,
        ProviderStatus.REJECTED,
    }),
}

# Expected events per state
# Maps state to the event type that triggers the next transition
EXPECTED_EVENTS: Final[dict[ProviderStatus, str | None]] = {
    ProviderStatus.INVITED: "SendMessageRequested",
    ProviderStatus.WAITING_RESPONSE: "ProviderResponseReceived",
    ProviderStatus.WAITING_DOCUMENT: "ProviderResponseReceived",
    ProviderStatus.DOCUMENT_PROCESSING: "DocumentProcessed",
    ProviderStatus.UNDER_REVIEW: "ScreeningCompleted",
    ProviderStatus.QUALIFIED: None,
    ProviderStatus.REJECTED: None,
    ProviderStatus.ESCALATED: None,
}


def validate_transition(
    current_status: ProviderStatus | str,
    new_status: ProviderStatus | str,
    *,
    raise_on_invalid: bool = True,
) -> bool:
    """
    Validate that a state transition is allowed.
    
    Args:
        current_status: Current provider status
        new_status: Desired next status
        raise_on_invalid: If True, raise exception on invalid transition
        
    Returns:
        True if transition is valid
        
    Raises:
        InvalidStateTransitionError: If transition is invalid and raise_on_invalid=True
    """
    # Convert strings to enums
    if isinstance(current_status, str):
        current_status = ProviderStatus.from_string(current_status)
    if isinstance(new_status, str):
        new_status = ProviderStatus.from_string(new_status)
    
    allowed = VALID_TRANSITIONS.get(current_status, frozenset())
    is_valid = new_status in allowed
    
    if not is_valid and raise_on_invalid:
        log.warning(
            "invalid_state_transition",
            current_status=current_status.value,
            new_status=new_status.value,
            allowed_transitions=[s.value for s in allowed],
        )
        raise InvalidStateTransitionError(
            current_status=current_status.value,
            new_status=new_status.value,
            allowed_transitions=[s.value for s in allowed],
        )
    
    return is_valid


def get_expected_event(status: ProviderStatus | str) -> str | None:
    """
    Get the expected event type for a given status.
    
    Args:
        status: Provider status
        
    Returns:
        Event type name or None for terminal states
    """
    if isinstance(status, str):
        status = ProviderStatus.from_string(status)
    return EXPECTED_EVENTS.get(status)
