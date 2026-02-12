"""
TextractCompletion Lambda Handler

Main entry point for processing Textract async job completion notifications.
Parses SNS→Textract events and emits DocumentProcessed events.

Trigger: SNS topic subscribed to Textract async job completion notifications
Output: EventBridge DocumentProcessed event

Flow:
1. Parse SNS notification with Textract job completion
2. Fetch Textract job results from GetDocumentAnalysis API
3. Extract campaign_id and provider_id from S3 path or job metadata
4. Classify document type from OCR content
5. Extract structured fields per document type
6. Emit DocumentProcessed event to EventBridge
"""

import json
import os
import re
import time
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from lambdas.textract_completion.document_processor import (
    DocumentExtractionResult,
    classify_document_type,
    extract_document_fields,
    get_key_value_pairs,
    get_textract_text_from_blocks,
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


# Environment configuration
EVENTBRIDGE_BUS_NAME = os.environ.get("RECRUITMENT_EVENTBRIDGE_BUS_NAME", "recruitment")
EVENTBRIDGE_SOURCE = os.environ.get(
    "RECRUITMENT_EVENTBRIDGE_SOURCE", "recruitment.lambdas.textract_completion"
)
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")


def _get_textract_client():
    """Get Textract client."""
    endpoint_url = os.environ.get("RECRUITMENT_TEXTRACT_ENDPOINT_URL")
    if endpoint_url:
        return boto3.client("textract", endpoint_url=endpoint_url, region_name=AWS_REGION)
    return boto3.client("textract", region_name=AWS_REGION)


def _get_eventbridge_client():
    """Get EventBridge client."""
    endpoint_url = os.environ.get("RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL")
    if endpoint_url:
        return boto3.client("events", endpoint_url=endpoint_url, region_name=AWS_REGION)
    return boto3.client("events", region_name=AWS_REGION)


def _parse_sns_notification(event: dict[str, Any]) -> dict[str, Any]:
    """
    Parse SNS notification to extract Textract completion data.
    
    Handles both:
    - Lambda trigger from SNS subscription
    - Direct SNS message format (for testing)
    
    Args:
        event: Lambda event payload
        
    Returns:
        Parsed Textract notification data
        
    Raises:
        ValueError: If notification cannot be parsed
    """
    # Handle SNS Lambda trigger format
    if "Records" in event:
        if not event["Records"]:
            raise ValueError("Empty Records in SNS event")
        
        record = event["Records"][0]
        if record.get("EventSource") != "aws:sns":
            raise ValueError(f"Unexpected event source: {record.get('EventSource')}")
        
        sns_message = record.get("Sns", {}).get("Message")
        if not sns_message:
            raise ValueError("No Message in SNS notification")
        
        return json.loads(sns_message)
    
    # Handle direct SNS message format
    if "Message" in event:
        return json.loads(event["Message"])
    
    # Handle direct Textract notification format (for testing)
    if "JobId" in event and "Status" in event:
        return event
    
    raise ValueError("Unable to parse Textract notification from event")


def _extract_ids_from_s3_path(s3_path: str) -> tuple[str | None, str | None]:
    """
    Extract campaign_id and provider_id from S3 document path.
    
    Expected path pattern: s3://bucket/documents/{campaign_id}/{provider_id}/...
    
    Args:
        s3_path: S3 URI of the document
        
    Returns:
        Tuple of (campaign_id, provider_id) or (None, None) if not found
    """
    # Pattern: documents/{campaign_id}/{provider_id}/
    pattern = r"documents/([^/]+)/([^/]+)/"
    match = re.search(pattern, s3_path)
    
    if match:
        return match.group(1), match.group(2)
    
    log.warning(
        "ids_not_in_s3_path",
        s3_path=s3_path,
        expected_pattern=pattern,
    )
    return None, None


def _get_textract_results(job_id: str) -> tuple[list[dict[str, Any]], str]:
    """
    Fetch Textract analysis results for a completed job.
    
    Handles pagination for large documents.
    
    Args:
        job_id: Textract job ID
        
    Returns:
        Tuple of (all_blocks, job_status)
        
    Raises:
        RuntimeError: If Textract API call fails
    """
    textract = _get_textract_client()
    all_blocks = []
    next_token = None
    job_status = "UNKNOWN"
    
    try:
        while True:
            # Build request parameters
            params = {"JobId": job_id}
            if next_token:
                params["NextToken"] = next_token
            
            response = textract.get_document_analysis(**params)
            
            job_status = response.get("JobStatus", "UNKNOWN")
            
            # Collect blocks from this page
            blocks = response.get("Blocks", [])
            all_blocks.extend(blocks)
            
            log.info(
                "textract_page_fetched",
                job_id=job_id,
                blocks_in_page=len(blocks),
                total_blocks=len(all_blocks),
            )
            
            # Check for more pages
            next_token = response.get("NextToken")
            if not next_token:
                break
        
        return all_blocks, job_status
        
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_msg = e.response.get("Error", {}).get("Message")
        
        log.error(
            "textract_get_results_failed",
            job_id=job_id,
            error_code=error_code,
            error_message=error_msg,
        )
        raise RuntimeError(f"Failed to get Textract results: {error_msg}") from e


def _get_document_metadata(job_id: str) -> dict[str, Any]:
    """
    Get document metadata from Textract job.
    
    Returns the document location (S3 bucket/key).
    
    Args:
        job_id: Textract job ID
        
    Returns:
        Document metadata dictionary
    """
    textract = _get_textract_client()
    
    try:
        # GetDocumentAnalysis returns document location in first call
        response = textract.get_document_analysis(JobId=job_id, MaxResults=1)
        
        metadata = {
            "job_id": job_id,
            "status": response.get("JobStatus"),
            "document_metadata": response.get("DocumentMetadata", {}),
        }
        
        # Try to get S3 location from response
        # Note: Textract doesn't return source location in response,
        # but we store it in the notification or job tags
        
        return metadata
        
    except ClientError as e:
        log.warning(
            "textract_metadata_fetch_failed",
            job_id=job_id,
            error=str(e),
        )
        return {"job_id": job_id}


def _build_document_processed_event(
    campaign_id: str,
    provider_id: str,
    document_s3_path: str,
    job_id: str,
    extraction_result: DocumentExtractionResult,
    trace_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build DocumentProcessed event payload.
    
    Matches schema in contracts/events.json.
    """
    event_detail = {
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "document_s3_path": document_s3_path,
        "document_type": extraction_result.document_type,
        "job_id": job_id,
        "ocr_text": extraction_result.ocr_text[:5000],  # Truncate for event size
        "extracted_fields": extraction_result.extracted_fields,
        "confidence_scores": extraction_result.confidence_scores,
    }
    
    if trace_context:
        event_detail["trace_context"] = trace_context
    
    return event_detail


def _emit_document_processed_event(detail: dict[str, Any]) -> str:
    """
    Emit DocumentProcessed event to EventBridge.
    
    Args:
        detail: Event detail payload
        
    Returns:
        EventBridge event ID
        
    Raises:
        RuntimeError: If event publication fails
    """
    client = _get_eventbridge_client()
    
    log.info(
        "emitting_document_processed",
        campaign_id=detail.get("campaign_id"),
        provider_id=detail.get("provider_id"),
        document_type=detail.get("document_type"),
    )
    
    try:
        response = client.put_events(
            Entries=[
                {
                    "EventBusName": EVENTBRIDGE_BUS_NAME,
                    "Source": EVENTBRIDGE_SOURCE,
                    "DetailType": "DocumentProcessed",
                    "Detail": json.dumps(detail),
                }
            ]
        )
    except ClientError as e:
        log.error("eventbridge_put_failed", error=str(e))
        raise RuntimeError(f"Failed to emit event: {e}") from e
    
    # Check for failed entries
    if response.get("FailedEntryCount", 0) > 0:
        failed = response["Entries"][0]
        error_msg = f"EventBridge entry failed: {failed.get('ErrorMessage')}"
        log.error(
            "eventbridge_entry_failed",
            error_code=failed.get("ErrorCode"),
            error_message=failed.get("ErrorMessage"),
        )
        raise RuntimeError(error_msg)
    
    event_id = response["Entries"][0].get("EventId", "unknown")
    log.info("event_emitted", event_id=event_id)
    
    return event_id


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda entry point for Textract completion handling.
    
    Processes Textract SNS notifications and emits DocumentProcessed events.
    
    Args:
        event: Lambda event (SNS notification or direct Textract event)
        context: Lambda execution context
        
    Returns:
        Processing result with status and metadata
    """
    start_time = time.time()
    
    log.info(
        "lambda_invoked",
        event_type=event.get("Records", [{}])[0].get("EventSource", "direct")
        if "Records" in event else "direct",
    )
    
    try:
        # Parse the Textract notification
        notification = _parse_sns_notification(event)
        
        job_id = notification.get("JobId")
        job_status = notification.get("Status")
        
        if not job_id:
            raise ValueError("No JobId in Textract notification")
        
        log.info(
            "textract_notification_parsed",
            job_id=job_id,
            status=job_status,
        )
        
        # Check job status
        if job_status != "SUCCEEDED":
            log.warning(
                "textract_job_not_successful",
                job_id=job_id,
                status=job_status,
            )
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "skipped",
                    "reason": f"Job status: {job_status}",
                    "job_id": job_id,
                }),
            }
        
        # Extract document S3 path from notification
        # Textract SNS notification includes DocumentLocation
        document_location = notification.get("DocumentLocation", {})
        s3_bucket = document_location.get("S3Bucket", "")
        s3_key = document_location.get("S3ObjectName", "")
        document_s3_path = f"s3://{s3_bucket}/{s3_key}" if s3_bucket and s3_key else ""
        
        # Extract campaign_id and provider_id from notification or S3 path
        campaign_id = notification.get("campaign_id")
        provider_id = notification.get("provider_id")
        
        if not campaign_id or not provider_id:
            # Try to extract from S3 path
            campaign_id, provider_id = _extract_ids_from_s3_path(document_s3_path)
        
        if not campaign_id or not provider_id:
            # Try to extract from job tags/metadata stored with the job
            job_tag = notification.get("JobTag", "")
            # JobTag format: campaign_id:provider_id
            if ":" in job_tag:
                parts = job_tag.split(":", 1)
                campaign_id = parts[0]
                provider_id = parts[1] if len(parts) > 1 else None
        
        if not campaign_id or not provider_id:
            raise ValueError(
                f"Could not determine campaign_id/provider_id from notification. "
                f"S3 path: {document_s3_path}, JobTag: {notification.get('JobTag')}"
            )
        
        log.info(
            "processing_document",
            job_id=job_id,
            campaign_id=campaign_id,
            provider_id=provider_id,
            document_s3_path=document_s3_path,
        )
        
        # Fetch Textract results
        blocks, result_status = _get_textract_results(job_id)
        
        if result_status != "SUCCEEDED":
            log.error(
                "textract_results_failed",
                job_id=job_id,
                status=result_status,
            )
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "failed",
                    "reason": f"Textract results status: {result_status}",
                    "job_id": job_id,
                }),
            }
        
        # Extract text from blocks
        ocr_text = get_textract_text_from_blocks(blocks)
        
        log.info(
            "ocr_text_extracted",
            job_id=job_id,
            text_length=len(ocr_text),
            block_count=len(blocks),
        )
        
        # Classify document type
        document_type, classification_confidence = classify_document_type(ocr_text)
        
        # Extract structured fields
        extraction_result = extract_document_fields(
            document_type=document_type,
            ocr_text=ocr_text,
            textract_blocks=blocks,
        )
        extraction_result.classification_confidence = classification_confidence
        
        # Get trace context if provided in notification
        trace_context = notification.get("trace_context")
        
        # Build and emit DocumentProcessed event
        event_detail = _build_document_processed_event(
            campaign_id=campaign_id,
            provider_id=provider_id,
            document_s3_path=document_s3_path,
            job_id=job_id,
            extraction_result=extraction_result,
            trace_context=trace_context,
        )
        
        event_id = _emit_document_processed_event(event_detail)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        log.info(
            "document_processed_successfully",
            job_id=job_id,
            campaign_id=campaign_id,
            provider_id=provider_id,
            document_type=document_type,
            fields_extracted=len(extraction_result.extracted_fields),
            event_id=event_id,
            duration_ms=duration_ms,
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "job_id": job_id,
                "event_id": event_id,
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "document_type": document_type,
                "fields_extracted": list(extraction_result.extracted_fields.keys()),
                "duration_ms": duration_ms,
            }),
        }
        
    except ValueError as e:
        log.error("validation_error", error=str(e))
        return {
            "statusCode": 400,
            "body": json.dumps({
                "status": "error",
                "error": str(e),
            }),
        }
        
    except Exception as e:
        log.exception("unexpected_error", error=str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "error",
                "error": str(e),
            }),
        }
