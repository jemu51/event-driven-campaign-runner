"""
Query Builder for Dormant Session Detection

Constructs GSI1 queries for finding providers in dormant states
that require follow-up based on time thresholds.

GSI1 Pattern:
- Partition Key (GSI1PK): "<status>#<expected_next_event>"
- Sort Key: last_contacted_at (Unix timestamp)

This enables efficient queries for:
- WAITING_RESPONSE + ProviderResponseReceived (no response to outreach)
- WAITING_DOCUMENT + ProviderResponseReceived (no document submitted)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import structlog

from agents.shared.state_machine import ProviderStatus

log = structlog.get_logger()


class FollowUpReason(str, Enum):
    """Reason for follow-up, matching contracts/events.json."""
    
    NO_RESPONSE = "no_response"
    MISSING_DOCUMENT = "missing_document"
    INCOMPLETE_INFO = "incomplete_info"


@dataclass(frozen=True)
class DormantSessionQuery:
    """
    Specification for a dormant session query.
    
    Each query targets a specific GSI1PK pattern (status + expected event)
    and includes the threshold timestamp and follow-up reason.
    """
    
    status: ProviderStatus
    expected_event: str
    follow_up_reason: FollowUpReason
    days_threshold: int
    description: str
    
    @property
    def gsi1pk(self) -> str:
        """Build the GSI1 partition key."""
        return f"{self.status.value}#{self.expected_event}"
    
    def get_threshold_timestamp(self, now: datetime | None = None) -> int:
        """
        Calculate the threshold timestamp for this query.
        
        Providers with last_contacted_at BEFORE this timestamp are dormant.
        
        Args:
            now: Current datetime (defaults to utcnow)
            
        Returns:
            Unix timestamp threshold
        """
        current = now or datetime.now(timezone.utc)
        threshold = current - timedelta(days=self.days_threshold)
        return int(threshold.timestamp())


@dataclass
class QueryResult:
    """
    Result of a dormant session query.
    
    Contains the provider states found and metadata about the query.
    """
    
    query: DormantSessionQuery
    providers: list[dict] = field(default_factory=list)  # Raw DynamoDB items
    threshold_timestamp: int = 0
    query_time_ms: float = 0.0
    error: str | None = None
    
    @property
    def count(self) -> int:
        """Number of dormant providers found."""
        return len(self.providers)
    
    @property
    def succeeded(self) -> bool:
        """Whether the query succeeded."""
        return self.error is None


# Default query configurations for dormant session detection
# These define which provider states to monitor and their thresholds
DEFAULT_DORMANT_QUERIES: list[DormantSessionQuery] = [
    DormantSessionQuery(
        status=ProviderStatus.WAITING_RESPONSE,
        expected_event="ProviderResponseReceived",
        follow_up_reason=FollowUpReason.NO_RESPONSE,
        days_threshold=3,
        description="Providers who haven't responded to initial outreach",
    ),
    DormantSessionQuery(
        status=ProviderStatus.WAITING_DOCUMENT,
        expected_event="ProviderResponseReceived",
        follow_up_reason=FollowUpReason.MISSING_DOCUMENT,
        days_threshold=2,
        description="Providers who acknowledged but haven't sent documents",
    ),
]


def build_dormant_session_queries(
    *,
    custom_thresholds: dict[ProviderStatus, int] | None = None,
    include_statuses: list[ProviderStatus] | None = None,
) -> list[DormantSessionQuery]:
    """
    Build the list of dormant session queries to execute.
    
    Args:
        custom_thresholds: Override default days thresholds per status
        include_statuses: Only include these statuses (default: all configured)
        
    Returns:
        List of DormantSessionQuery specifications
    """
    queries = []
    
    for default_query in DEFAULT_DORMANT_QUERIES:
        # Filter by status if specified
        if include_statuses and default_query.status not in include_statuses:
            continue
        
        # Apply custom threshold if specified
        threshold = (
            custom_thresholds.get(default_query.status, default_query.days_threshold)
            if custom_thresholds
            else default_query.days_threshold
        )
        
        # Create query with potentially modified threshold
        if threshold != default_query.days_threshold:
            queries.append(
                DormantSessionQuery(
                    status=default_query.status,
                    expected_event=default_query.expected_event,
                    follow_up_reason=default_query.follow_up_reason,
                    days_threshold=threshold,
                    description=default_query.description,
                )
            )
        else:
            queries.append(default_query)
    
    log.debug(
        "dormant_session_queries_built",
        query_count=len(queries),
        statuses=[q.status.value for q in queries],
    )
    
    return queries


def calculate_follow_up_number(
    last_contacted_at: int,
    days_threshold: int,
    max_follow_ups: int = 3,
) -> int:
    """
    Calculate which follow-up number this is based on time elapsed.
    
    The follow-up number increases as more threshold periods pass:
    - 1x threshold = follow-up #1
    - 2x threshold = follow-up #2
    - 3x+ threshold = follow-up #3 (max)
    
    Args:
        last_contacted_at: Unix timestamp of last contact
        days_threshold: Days for first follow-up
        max_follow_ups: Maximum follow-up number (default: 3)
        
    Returns:
        Follow-up number (1-3)
    """
    now = int(datetime.now(timezone.utc).timestamp())
    days_elapsed = (now - last_contacted_at) / (24 * 60 * 60)
    
    # Each threshold period = one more follow-up
    follow_up_num = int(days_elapsed / days_threshold)
    
    # Clamp to valid range [1, max_follow_ups]
    return max(1, min(follow_up_num, max_follow_ups))


def days_since_contact(last_contacted_at: int) -> int:
    """
    Calculate days since last contact.
    
    Args:
        last_contacted_at: Unix timestamp of last contact
        
    Returns:
        Number of complete days elapsed
    """
    now = int(datetime.now(timezone.utc).timestamp())
    seconds_elapsed = now - last_contacted_at
    return int(seconds_elapsed / (24 * 60 * 60))
