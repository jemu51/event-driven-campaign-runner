"""
SendFollowUps Lambda

Periodic Lambda triggered by EventBridge Scheduled Rule to detect
dormant provider sessions and emit FollowUpTriggered events.

Components:
- handler: Lambda entry point for scheduled trigger
- query_builder: GSI1 query construction for dormant session detection

Flow:
1. Triggered by scheduled EventBridge rule (e.g., daily at midnight)
2. Query GSI1 for providers in WAITING_* states past threshold
3. Determine follow-up reason and count for each dormant provider
4. Emit FollowUpTriggered events to wake Communication Agent
5. Return summary of follow-ups triggered
"""

from lambdas.send_follow_ups.handler import lambda_handler
from lambdas.send_follow_ups.query_builder import (
    DormantSessionQuery,
    QueryResult,
    build_dormant_session_queries,
)

__all__ = [
    "lambda_handler",
    "DormantSessionQuery",
    "QueryResult",
    "build_dormant_session_queries",
]
