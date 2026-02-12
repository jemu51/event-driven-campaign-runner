"""
Unit tests for SendFollowUps Lambda handler.

Tests cover:
- Query builder: query_builder.py
- Handler: handler.py
"""

from datetime import datetime, timezone

import pytest

from agents.shared.state_machine import ProviderStatus


# ============================================================================
# Query Builder Tests
# ============================================================================

class TestFollowUpReason:
    """Tests for FollowUpReason enum."""
    
    def test_follow_up_reason_values(self):
        """Test FollowUpReason enum values."""
        from lambdas.send_follow_ups.query_builder import FollowUpReason
        
        assert FollowUpReason.NO_RESPONSE.value == "no_response"
        assert FollowUpReason.MISSING_DOCUMENT.value == "missing_document"
        assert FollowUpReason.INCOMPLETE_INFO.value == "incomplete_info"
    
    def test_follow_up_reason_is_string(self):
        """Test FollowUpReason extends str."""
        from lambdas.send_follow_ups.query_builder import FollowUpReason
        
        assert isinstance(FollowUpReason.NO_RESPONSE, str)
        assert FollowUpReason.NO_RESPONSE == "no_response"


class TestDormantSessionQuery:
    """Tests for DormantSessionQuery dataclass."""
    
    def test_dormant_session_query_gsi1pk(self):
        """Test GSI1PK property construction."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test query",
        )
        
        assert query.gsi1pk == "WAITING_RESPONSE#ProviderResponseReceived"
    
    def test_dormant_session_query_threshold_timestamp(self):
        """Test threshold timestamp calculation."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test query",
        )
        
        now = datetime(2024, 1, 15, 12, 0, 0)
        threshold = query.get_threshold_timestamp(now)
        
        # Should be 3 days before now
        expected = datetime(2024, 1, 12, 12, 0, 0)
        assert threshold == int(expected.timestamp())
    
    def test_dormant_session_query_frozen(self):
        """Test DormantSessionQuery is immutable."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test query",
        )
        
        with pytest.raises(Exception):
            query.days_threshold = 5


class TestQueryResult:
    """Tests for QueryResult dataclass."""
    
    def test_query_result_count(self):
        """Test QueryResult.count property."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            QueryResult,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test",
        )
        
        result = QueryResult(
            query=query,
            providers=[{"PK": "session1"}, {"PK": "session2"}],
        )
        
        assert result.count == 2
    
    def test_query_result_succeeded(self):
        """Test QueryResult.succeeded property."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            QueryResult,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test",
        )
        
        # Success case
        result = QueryResult(query=query, providers=[])
        assert result.succeeded is True
        
        # Failure case
        result_error = QueryResult(query=query, error="Query failed")
        assert result_error.succeeded is False


class TestBuildDormantSessionQueries:
    """Tests for build_dormant_session_queries function."""
    
    def test_build_default_queries(self):
        """Test building default dormant session queries."""
        from lambdas.send_follow_ups.query_builder import build_dormant_session_queries
        
        queries = build_dormant_session_queries()
        
        # Should have at least 2 default queries
        assert len(queries) >= 2
        
        # Check for expected query types
        statuses = [q.status for q in queries]
        assert ProviderStatus.WAITING_RESPONSE in statuses
        assert ProviderStatus.WAITING_DOCUMENT in statuses
    
    def test_build_queries_with_custom_thresholds(self):
        """Test building queries with custom thresholds."""
        from lambdas.send_follow_ups.query_builder import build_dormant_session_queries
        
        custom_thresholds = {
            ProviderStatus.WAITING_RESPONSE: 5,  # 5 days instead of default 3
        }
        
        queries = build_dormant_session_queries(custom_thresholds=custom_thresholds)
        
        waiting_response_query = next(
            q for q in queries if q.status == ProviderStatus.WAITING_RESPONSE
        )
        assert waiting_response_query.days_threshold == 5
    
    def test_build_queries_with_status_filter(self):
        """Test building queries for specific statuses only."""
        from lambdas.send_follow_ups.query_builder import build_dormant_session_queries
        
        queries = build_dormant_session_queries(
            include_statuses=[ProviderStatus.WAITING_RESPONSE]
        )
        
        # Should only include WAITING_RESPONSE queries
        for query in queries:
            assert query.status == ProviderStatus.WAITING_RESPONSE


class TestDefaultDormantQueries:
    """Tests for DEFAULT_DORMANT_QUERIES configuration."""
    
    def test_default_queries_exist(self):
        """Test that default queries are defined."""
        from lambdas.send_follow_ups.query_builder import DEFAULT_DORMANT_QUERIES
        
        assert len(DEFAULT_DORMANT_QUERIES) >= 1
    
    def test_default_queries_have_valid_statuses(self):
        """Test that default queries use valid ProviderStatus values."""
        from lambdas.send_follow_ups.query_builder import DEFAULT_DORMANT_QUERIES
        
        for query in DEFAULT_DORMANT_QUERIES:
            assert isinstance(query.status, ProviderStatus)
    
    def test_default_queries_have_descriptions(self):
        """Test that all default queries have descriptions."""
        from lambdas.send_follow_ups.query_builder import DEFAULT_DORMANT_QUERIES
        
        for query in DEFAULT_DORMANT_QUERIES:
            assert query.description
            assert len(query.description) > 10


# ============================================================================
# Handler Tests
# ============================================================================

class TestFollowUpEvent:
    """Tests for FollowUpEvent dataclass."""
    
    def test_follow_up_event_to_detail(self):
        """Test FollowUpEvent.to_eventbridge_detail() method."""
        from lambdas.send_follow_ups.handler import FollowUpEvent
        from lambdas.send_follow_ups.query_builder import FollowUpReason
        
        event = FollowUpEvent(
            campaign_id="camp-001",
            provider_id="prov-001",
            reason=FollowUpReason.NO_RESPONSE,
            follow_up_number=2,
            days_since_last_contact=5,
            current_status="WAITING_RESPONSE",
        )
        
        detail = event.to_eventbridge_detail()
        
        assert detail["campaign_id"] == "camp-001"
        assert detail["provider_id"] == "prov-001"
        assert detail["reason"] == "no_response"
        assert detail["follow_up_number"] == 2
        assert detail["days_since_last_contact"] == 5
        assert detail["current_status"] == "WAITING_RESPONSE"
    
    def test_follow_up_event_with_trace(self):
        """Test FollowUpEvent with trace context."""
        from lambdas.send_follow_ups.handler import FollowUpEvent
        from lambdas.send_follow_ups.query_builder import FollowUpReason
        
        event = FollowUpEvent(
            campaign_id="camp-001",
            provider_id="prov-001",
            reason=FollowUpReason.MISSING_DOCUMENT,
            follow_up_number=1,
            days_since_last_contact=3,
            current_status="WAITING_DOCUMENT",
            trace_context={"trace_id": "abc123", "span_id": "def456"},
        )
        
        detail = event.to_eventbridge_detail()
        
        assert "trace_context" in detail
        assert detail["trace_context"]["trace_id"] == "abc123"


class TestFollowUpResult:
    """Tests for FollowUpResult dataclass."""
    
    def test_follow_up_result_succeeded_with_results(self):
        """Test succeeded property with successful queries."""
        from lambdas.send_follow_ups.handler import FollowUpResult
        
        result = FollowUpResult(
            queries_executed=3,
            queries_succeeded=3,
            dormant_providers_found=10,
            follow_ups_emitted=10,
        )
        
        assert result.succeeded is True
    
    def test_follow_up_result_succeeded_with_zero_queries(self):
        """Test succeeded property with no queries to execute."""
        from lambdas.send_follow_ups.handler import FollowUpResult
        
        result = FollowUpResult(queries_executed=0, queries_succeeded=0)
        
        assert result.succeeded is True
    
    def test_follow_up_result_failed(self):
        """Test succeeded property when no queries succeeded."""
        from lambdas.send_follow_ups.handler import FollowUpResult
        
        result = FollowUpResult(
            queries_executed=3,
            queries_succeeded=0,
            errors=["Query 1 failed", "Query 2 failed"],
        )
        
        assert result.succeeded is False


# ============================================================================
# Integration Tests
# ============================================================================

class TestSendFollowUpsIntegration:
    """Integration tests for SendFollowUps components."""
    
    def test_query_threshold_is_past(self):
        """Test that query threshold correctly calculates past timestamp."""
        from lambdas.send_follow_ups.query_builder import (
            DormantSessionQuery,
            FollowUpReason,
        )
        
        query = DormantSessionQuery(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_event="ProviderResponseReceived",
            follow_up_reason=FollowUpReason.NO_RESPONSE,
            days_threshold=3,
            description="Test",
        )
        
        now = datetime.now(timezone.utc)
        threshold = query.get_threshold_timestamp(now)
        
        # Threshold should be in the past
        assert threshold < int(now.timestamp())
        
        # Should be approximately 3 days ago (within 1 second tolerance)
        expected_seconds_ago = 3 * 24 * 60 * 60
        actual_seconds_ago = int(now.timestamp()) - threshold
        assert abs(actual_seconds_ago - expected_seconds_ago) < 2
