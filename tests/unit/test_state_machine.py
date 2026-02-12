"""
Test State Machine

Unit tests for provider state machine transitions and validation.
Tests cover all states, transitions, and edge cases.
"""

import pytest

from agents.shared.exceptions import InvalidStateTransitionError
from agents.shared.state_machine import (
    EXPECTED_EVENTS,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    ProviderStatus,
    get_expected_event,
    validate_transition,
)


class TestProviderStatus:
    """Tests for ProviderStatus enum."""

    def test_all_states_defined(self):
        """Verify all expected states are defined."""
        expected_states = [
            "INVITED",
            "WAITING_RESPONSE",
            "WAITING_DOCUMENT",
            "DOCUMENT_PROCESSING",
            "UNDER_REVIEW",
            "QUALIFIED",
            "REJECTED",
            "ESCALATED",
        ]
        actual_states = [s.value for s in ProviderStatus]
        assert sorted(actual_states) == sorted(expected_states)

    def test_from_string_valid(self):
        """Test conversion from valid string."""
        assert ProviderStatus.from_string("INVITED") == ProviderStatus.INVITED
        assert ProviderStatus.from_string("qualified") == ProviderStatus.QUALIFIED
        assert ProviderStatus.from_string("Waiting_Response") == ProviderStatus.WAITING_RESPONSE

    def test_from_string_invalid(self):
        """Test conversion from invalid string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid provider status"):
            ProviderStatus.from_string("INVALID_STATE")

        with pytest.raises(ValueError, match="Invalid provider status"):
            ProviderStatus.from_string("")

    def test_is_terminal_property(self):
        """Test is_terminal property for each status."""
        # Terminal states
        assert ProviderStatus.QUALIFIED.is_terminal is True
        assert ProviderStatus.REJECTED.is_terminal is True
        
        # Non-terminal states
        assert ProviderStatus.INVITED.is_terminal is False
        assert ProviderStatus.WAITING_RESPONSE.is_terminal is False
        assert ProviderStatus.WAITING_DOCUMENT.is_terminal is False
        assert ProviderStatus.DOCUMENT_PROCESSING.is_terminal is False
        assert ProviderStatus.UNDER_REVIEW.is_terminal is False
        assert ProviderStatus.ESCALATED.is_terminal is False


class TestTerminalStates:
    """Tests for terminal state definition."""

    def test_terminal_states_are_qualified_and_rejected(self):
        """Verify QUALIFIED and REJECTED are the only terminal states."""
        assert ProviderStatus.QUALIFIED in TERMINAL_STATES
        assert ProviderStatus.REJECTED in TERMINAL_STATES
        assert len(TERMINAL_STATES) == 2

    def test_terminal_states_have_no_transitions(self):
        """Terminal states should have empty transition sets."""
        for status in TERMINAL_STATES:
            assert VALID_TRANSITIONS[status] == frozenset()


class TestValidTransitions:
    """Tests for VALID_TRANSITIONS mapping."""

    def test_invited_transitions(self):
        """INVITED can only transition to WAITING_RESPONSE."""
        allowed = VALID_TRANSITIONS[ProviderStatus.INVITED]
        assert allowed == frozenset({ProviderStatus.WAITING_RESPONSE})

    def test_waiting_response_transitions(self):
        """WAITING_RESPONSE can transition to multiple states."""
        allowed = VALID_TRANSITIONS[ProviderStatus.WAITING_RESPONSE]
        expected = frozenset({
            ProviderStatus.WAITING_DOCUMENT,
            ProviderStatus.DOCUMENT_PROCESSING,
            ProviderStatus.QUALIFIED,
            ProviderStatus.REJECTED,
            ProviderStatus.UNDER_REVIEW,
        })
        assert allowed == expected

    def test_waiting_document_transitions(self):
        """WAITING_DOCUMENT transitions."""
        allowed = VALID_TRANSITIONS[ProviderStatus.WAITING_DOCUMENT]
        expected = frozenset({
            ProviderStatus.DOCUMENT_PROCESSING,
            ProviderStatus.REJECTED,
            ProviderStatus.ESCALATED,
        })
        assert allowed == expected

    def test_document_processing_transitions(self):
        """DOCUMENT_PROCESSING transitions."""
        allowed = VALID_TRANSITIONS[ProviderStatus.DOCUMENT_PROCESSING]
        expected = frozenset({
            ProviderStatus.UNDER_REVIEW,
            ProviderStatus.WAITING_DOCUMENT,
            ProviderStatus.QUALIFIED,
            ProviderStatus.REJECTED,
        })
        assert allowed == expected

    def test_under_review_transitions(self):
        """UNDER_REVIEW transitions."""
        allowed = VALID_TRANSITIONS[ProviderStatus.UNDER_REVIEW]
        expected = frozenset({
            ProviderStatus.QUALIFIED,
            ProviderStatus.REJECTED,
            ProviderStatus.ESCALATED,
        })
        assert allowed == expected

    def test_escalated_transitions(self):
        """ESCALATED can resolve to terminal states."""
        allowed = VALID_TRANSITIONS[ProviderStatus.ESCALATED]
        expected = frozenset({
            ProviderStatus.QUALIFIED,
            ProviderStatus.REJECTED,
        })
        assert allowed == expected

    def test_all_states_have_transitions_defined(self):
        """Every status should have an entry in VALID_TRANSITIONS."""
        for status in ProviderStatus:
            assert status in VALID_TRANSITIONS


class TestValidateTransition:
    """Tests for validate_transition function."""

    def test_valid_transition_invited_to_waiting(self):
        """Valid: INVITED → WAITING_RESPONSE."""
        result = validate_transition(
            ProviderStatus.INVITED,
            ProviderStatus.WAITING_RESPONSE,
        )
        assert result is True

    def test_valid_transition_waiting_to_document_processing(self):
        """Valid: WAITING_RESPONSE → DOCUMENT_PROCESSING."""
        result = validate_transition(
            ProviderStatus.WAITING_RESPONSE,
            ProviderStatus.DOCUMENT_PROCESSING,
        )
        assert result is True

    def test_valid_transition_document_processing_to_qualified(self):
        """Valid: DOCUMENT_PROCESSING → QUALIFIED."""
        result = validate_transition(
            ProviderStatus.DOCUMENT_PROCESSING,
            ProviderStatus.QUALIFIED,
        )
        assert result is True

    def test_valid_transition_with_strings(self):
        """validate_transition accepts string inputs."""
        result = validate_transition("INVITED", "WAITING_RESPONSE")
        assert result is True

    def test_valid_transition_case_insensitive(self):
        """String inputs are case-insensitive."""
        result = validate_transition("invited", "waiting_response")
        assert result is True

    def test_invalid_transition_raises_error(self):
        """Invalid transition raises InvalidStateTransitionError."""
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_transition(
                ProviderStatus.INVITED,
                ProviderStatus.QUALIFIED,  # Cannot skip to QUALIFIED
            )
        
        error = exc_info.value
        assert error.current_status == "INVITED"
        assert error.new_status == "QUALIFIED"
        assert "WAITING_RESPONSE" in error.allowed_transitions

    def test_invalid_transition_no_raise(self):
        """Invalid transition returns False when raise_on_invalid=False."""
        result = validate_transition(
            ProviderStatus.INVITED,
            ProviderStatus.QUALIFIED,
            raise_on_invalid=False,
        )
        assert result is False

    def test_terminal_state_cannot_transition(self):
        """Terminal states cannot transition anywhere."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(
                ProviderStatus.QUALIFIED,
                ProviderStatus.REJECTED,
            )

        with pytest.raises(InvalidStateTransitionError):
            validate_transition(
                ProviderStatus.REJECTED,
                ProviderStatus.QUALIFIED,
            )

    def test_invalid_string_raises_value_error(self):
        """Invalid string status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid provider status"):
            validate_transition("NOT_A_STATUS", "QUALIFIED")


class TestExpectedEvents:
    """Tests for expected events mapping."""

    def test_invited_expects_send_message(self):
        """INVITED expects SendMessageRequested."""
        assert EXPECTED_EVENTS[ProviderStatus.INVITED] == "SendMessageRequested"

    def test_waiting_response_expects_provider_response(self):
        """WAITING_RESPONSE expects ProviderResponseReceived."""
        assert EXPECTED_EVENTS[ProviderStatus.WAITING_RESPONSE] == "ProviderResponseReceived"

    def test_waiting_document_expects_provider_response(self):
        """WAITING_DOCUMENT expects ProviderResponseReceived."""
        assert EXPECTED_EVENTS[ProviderStatus.WAITING_DOCUMENT] == "ProviderResponseReceived"

    def test_document_processing_expects_document_processed(self):
        """DOCUMENT_PROCESSING expects DocumentProcessed."""
        assert EXPECTED_EVENTS[ProviderStatus.DOCUMENT_PROCESSING] == "DocumentProcessed"

    def test_under_review_expects_screening_completed(self):
        """UNDER_REVIEW expects ScreeningCompleted."""
        assert EXPECTED_EVENTS[ProviderStatus.UNDER_REVIEW] == "ScreeningCompleted"

    def test_terminal_states_expect_no_event(self):
        """Terminal states expect no event."""
        assert EXPECTED_EVENTS[ProviderStatus.QUALIFIED] is None
        assert EXPECTED_EVENTS[ProviderStatus.REJECTED] is None

    def test_escalated_expects_no_event(self):
        """ESCALATED expects no event (manual resolution)."""
        assert EXPECTED_EVENTS[ProviderStatus.ESCALATED] is None


class TestGetExpectedEvent:
    """Tests for get_expected_event function."""

    def test_get_expected_event_with_enum(self):
        """get_expected_event works with enum input."""
        assert get_expected_event(ProviderStatus.INVITED) == "SendMessageRequested"

    def test_get_expected_event_with_string(self):
        """get_expected_event works with string input."""
        assert get_expected_event("WAITING_RESPONSE") == "ProviderResponseReceived"

    def test_get_expected_event_case_insensitive(self):
        """get_expected_event is case-insensitive for strings."""
        assert get_expected_event("document_processing") == "DocumentProcessed"

    def test_get_expected_event_terminal_returns_none(self):
        """get_expected_event returns None for terminal states."""
        assert get_expected_event(ProviderStatus.QUALIFIED) is None
        assert get_expected_event(ProviderStatus.REJECTED) is None


class TestStateMachineAlignment:
    """Tests verifying alignment with contracts/state_machine.json."""

    def test_transition_count_matches_json(self):
        """Verify number of non-terminal states matches json."""
        # From state_machine.json: 8 states total, 2 terminal
        assert len(ProviderStatus) == 8
        assert len(TERMINAL_STATES) == 2

    def test_escalated_is_not_terminal(self):
        """ESCALATED can be resolved, so not terminal."""
        # This aligns with state_machine.json which shows ESCALATED
        # can transition to QUALIFIED or REJECTED
        assert ProviderStatus.ESCALATED not in TERMINAL_STATES
        assert len(VALID_TRANSITIONS[ProviderStatus.ESCALATED]) == 2

    def test_happy_path_workflow(self):
        """Test full happy path: INVITED → QUALIFIED."""
        # Provider gets invited
        current = ProviderStatus.INVITED
        
        # Email sent, waiting for response
        assert validate_transition(current, ProviderStatus.WAITING_RESPONSE)
        current = ProviderStatus.WAITING_RESPONSE
        
        # Provider responds with document
        assert validate_transition(current, ProviderStatus.DOCUMENT_PROCESSING)
        current = ProviderStatus.DOCUMENT_PROCESSING
        
        # Document validates successfully
        assert validate_transition(current, ProviderStatus.QUALIFIED)
        current = ProviderStatus.QUALIFIED
        
        # Cannot transition from terminal
        assert current.is_terminal

    def test_rejection_workflow(self):
        """Test rejection path: INVITED → REJECTED."""
        current = ProviderStatus.INVITED
        
        # Email sent
        assert validate_transition(current, ProviderStatus.WAITING_RESPONSE)
        current = ProviderStatus.WAITING_RESPONSE
        
        # Provider declines
        assert validate_transition(current, ProviderStatus.REJECTED)
        current = ProviderStatus.REJECTED
        
        assert current.is_terminal

    def test_document_retry_workflow(self):
        """Test document retry: DOCUMENT_PROCESSING → WAITING_DOCUMENT → DOCUMENT_PROCESSING."""
        current = ProviderStatus.DOCUMENT_PROCESSING
        
        # Document invalid, need new upload
        assert validate_transition(current, ProviderStatus.WAITING_DOCUMENT)
        current = ProviderStatus.WAITING_DOCUMENT
        
        # New document uploaded
        assert validate_transition(current, ProviderStatus.DOCUMENT_PROCESSING)
        current = ProviderStatus.DOCUMENT_PROCESSING

    def test_escalation_workflow(self):
        """Test escalation and resolution."""
        # From WAITING_DOCUMENT to ESCALATED
        assert validate_transition(
            ProviderStatus.WAITING_DOCUMENT,
            ProviderStatus.ESCALATED,
        )
        
        # ESCALATED can be resolved to QUALIFIED
        assert validate_transition(
            ProviderStatus.ESCALATED,
            ProviderStatus.QUALIFIED,
        )
        
        # Or resolved to REJECTED
        assert validate_transition(
            ProviderStatus.ESCALATED,
            ProviderStatus.REJECTED,
        )
