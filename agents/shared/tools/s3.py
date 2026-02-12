"""
S3 Tools

Idempotent tools for document storage in S3.
Supports the document artifacts workflow for recruitment screening.
"""

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import BinaryIO
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
import structlog

from agents.shared.config import get_settings
from agents.shared.exceptions import DocumentProcessingError, S3Error

log = structlog.get_logger()


def _get_client():
    """Get S3 client."""
    settings = get_settings()
    return boto3.client("s3", **settings.s3_config)


def _get_resource():
    """Get S3 resource."""
    settings = get_settings()
    return boto3.resource("s3", **settings.s3_config)


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """
    Parse an S3 URI into bucket and key.
    
    Args:
        s3_uri: S3 URI (s3://bucket/key)
        
    Returns:
        Tuple of (bucket, key)
        
    Raises:
        ValueError: If URI is invalid
    """
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 URI scheme: {parsed.scheme}")
    
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    
    return bucket, key


def _build_document_key(
    campaign_id: str,
    provider_id: str,
    filename: str,
    *,
    prefix: str | None = None,
) -> str:
    """
    Build a standardized S3 key for a document.
    
    Format: {prefix}{campaign_id}/{provider_id}/{timestamp}_{filename}
    """
    settings = get_settings()
    doc_prefix = prefix or settings.s3_documents_prefix
    
    # Add timestamp to avoid overwrites
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # Sanitize filename
    safe_filename = PurePosixPath(filename).name  # Remove any path components
    
    key = f"{doc_prefix}{campaign_id}/{provider_id}/{timestamp}_{safe_filename}"
    return key


def upload_document(
    content: bytes | BinaryIO,
    campaign_id: str,
    provider_id: str,
    filename: str,
    *,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> str:
    """
    Upload a document to S3.
    
    Documents are stored with a standardized path structure:
    documents/{campaign_id}/{provider_id}/{timestamp}_{filename}
    
    Args:
        content: File content (bytes or file-like object)
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        filename: Original filename
        content_type: MIME type
        metadata: Optional metadata dict
        
    Returns:
        S3 URI of uploaded document
        
    Raises:
        DocumentProcessingError: If upload fails
    """
    settings = get_settings()
    client = _get_client()
    
    key = _build_document_key(campaign_id, provider_id, filename)
    
    log.info(
        "uploading_document",
        campaign_id=campaign_id,
        provider_id=provider_id,
        filename=filename,
        content_type=content_type,
    )
    
    put_params = {
        "Bucket": settings.s3_bucket_name,
        "Key": key,
        "ContentType": content_type,
    }
    
    if metadata:
        put_params["Metadata"] = metadata
    
    try:
        if isinstance(content, bytes):
            put_params["Body"] = content
        else:
            put_params["Body"] = content.read()
        
        client.put_object(**put_params)
        
        s3_uri = f"s3://{settings.s3_bucket_name}/{key}"
        
        log.info(
            "document_uploaded",
            s3_uri=s3_uri,
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        
        return s3_uri
    
    except ClientError as e:
        log.error(
            "s3_upload_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            filename=filename,
            error=str(e),
        )
        raise DocumentProcessingError(
            document_path=filename,
            operation="upload",
            error_message=str(e),
        ) from e


def upload_from_path(
    file_path: str,
    campaign_id: str,
    provider_id: str,
    *,
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    """
    Upload a document from a local file path.
    
    Args:
        file_path: Local file path
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        content_type: MIME type (inferred from extension if not provided)
        metadata: Optional metadata dict
        
    Returns:
        S3 URI of uploaded document
    """
    import mimetypes
    from pathlib import Path
    
    path = Path(file_path)
    filename = path.name
    
    if content_type is None:
        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"
    
    with open(file_path, "rb") as f:
        return upload_document(
            content=f,
            campaign_id=campaign_id,
            provider_id=provider_id,
            filename=filename,
            content_type=content_type,
            metadata=metadata,
        )


def download_document(s3_uri: str) -> bytes:
    """
    Download a document from S3.
    
    Args:
        s3_uri: S3 URI (s3://bucket/key)
        
    Returns:
        Document content as bytes
        
    Raises:
        DocumentProcessingError: If download fails
    """
    client = _get_client()
    
    try:
        bucket, key = _parse_s3_uri(s3_uri)
    except ValueError as e:
        raise DocumentProcessingError(
            document_path=s3_uri,
            operation="download",
            error_message=str(e),
        ) from e
    
    log.debug(
        "downloading_document",
        s3_uri=s3_uri,
    )
    
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        
        log.debug(
            "document_downloaded",
            s3_uri=s3_uri,
            size_bytes=len(content),
        )
        
        return content
    
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        
        if error_code == "NoSuchKey":
            log.warning("document_not_found", s3_uri=s3_uri)
        else:
            log.error("s3_download_failed", s3_uri=s3_uri, error=str(e))
        
        raise DocumentProcessingError(
            document_path=s3_uri,
            operation="download",
            error_message=str(e),
        ) from e


def download_to_path(s3_uri: str, local_path: str) -> str:
    """
    Download a document from S3 to a local file.
    
    Args:
        s3_uri: S3 URI
        local_path: Local file path to write to
        
    Returns:
        Local file path
    """
    content = download_document(s3_uri)
    
    with open(local_path, "wb") as f:
        f.write(content)
    
    return local_path


def list_documents(
    campaign_id: str,
    provider_id: str | None = None,
    *,
    prefix: str | None = None,
    max_results: int = 1000,
) -> list[dict]:
    """
    List documents for a campaign or provider.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Optional provider identifier to filter by
        prefix: Optional prefix override
        max_results: Maximum results to return
        
    Returns:
        List of document metadata dicts with keys:
        - s3_uri: S3 URI
        - filename: Original filename (extracted from key)
        - size_bytes: File size
        - last_modified: Datetime of last modification
    """
    settings = get_settings()
    client = _get_client()
    
    doc_prefix = prefix or settings.s3_documents_prefix
    
    if provider_id:
        search_prefix = f"{doc_prefix}{campaign_id}/{provider_id}/"
    else:
        search_prefix = f"{doc_prefix}{campaign_id}/"
    
    log.debug(
        "listing_documents",
        campaign_id=campaign_id,
        provider_id=provider_id,
        prefix=search_prefix,
    )
    
    try:
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=settings.s3_bucket_name,
            Prefix=search_prefix,
            PaginationConfig={"MaxItems": max_results},
        )
        
        documents = []
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Extract filename from key (after timestamp prefix)
                parts = key.split("/")
                filename_with_ts = parts[-1] if parts else key
                # Remove timestamp prefix if present (format: YYYYMMDD_HHMMSS_)
                if "_" in filename_with_ts:
                    # Find second underscore (after date and time)
                    first_us = filename_with_ts.find("_")
                    second_us = filename_with_ts.find("_", first_us + 1)
                    if second_us > 0:
                        filename = filename_with_ts[second_us + 1:]
                    else:
                        filename = filename_with_ts
                else:
                    filename = filename_with_ts
                
                documents.append({
                    "s3_uri": f"s3://{settings.s3_bucket_name}/{key}",
                    "key": key,
                    "filename": filename,
                    "size_bytes": obj["Size"],
                    "last_modified": obj["LastModified"],
                })
        
        log.debug(
            "documents_listed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            count=len(documents),
        )
        
        return documents
    
    except ClientError as e:
        log.error(
            "s3_list_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
        )
        raise S3Error(
            operation="list",
            bucket=settings.s3_bucket_name,
            key=search_prefix,
            error_message=str(e),
        ) from e


def get_document_url(
    s3_uri: str,
    *,
    expires_in: int = 3600,
) -> str:
    """
    Generate a presigned URL for document access.
    
    Args:
        s3_uri: S3 URI of the document
        expires_in: URL expiration time in seconds (default: 1 hour)
        
    Returns:
        Presigned URL
    """
    client = _get_client()
    
    try:
        bucket, key = _parse_s3_uri(s3_uri)
    except ValueError as e:
        raise S3Error(
            operation="presign",
            bucket="unknown",
            key=s3_uri,
            error_message=str(e),
        ) from e
    
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        
        log.debug(
            "presigned_url_generated",
            s3_uri=s3_uri,
            expires_in=expires_in,
        )
        
        return url
    
    except ClientError as e:
        log.error(
            "presign_failed",
            s3_uri=s3_uri,
            error=str(e),
        )
        raise S3Error(
            operation="presign",
            bucket=bucket,
            key=key,
            error_message=str(e),
        ) from e


def delete_document(s3_uri: str) -> bool:
    """
    Delete a document from S3.
    
    Args:
        s3_uri: S3 URI of the document
        
    Returns:
        True if deleted successfully
    """
    client = _get_client()
    
    try:
        bucket, key = _parse_s3_uri(s3_uri)
    except ValueError as e:
        raise S3Error(
            operation="delete",
            bucket="unknown",
            key=s3_uri,
            error_message=str(e),
        ) from e
    
    log.info(
        "deleting_document",
        s3_uri=s3_uri,
    )
    
    try:
        client.delete_object(Bucket=bucket, Key=key)
        
        log.info(
            "document_deleted",
            s3_uri=s3_uri,
        )
        
        return True
    
    except ClientError as e:
        log.error(
            "s3_delete_failed",
            s3_uri=s3_uri,
            error=str(e),
        )
        raise S3Error(
            operation="delete",
            bucket=bucket,
            key=key,
            error_message=str(e),
        ) from e
