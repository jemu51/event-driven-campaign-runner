#!/bin/bash

################################################################################
# Lambda Deployment Package Builder: screening Agent
# 
# This script automates the complete process of packaging the screening
# agent for AWS Lambda deployment. It:
# 1. Creates/uses Python 3.12 venv (AWS supported version)
# 2. Installs runtime dependencies (Strands AI, LLM, Textract support)
# 3. Copies source code from agents/screening, agents/shared, contracts/
# 4. Creates AWS Lambda deployment ZIP
#
# Usage: ./build_lambda.sh
# Run from: {root}/lambda_deployment/screening/
################################################################################

set -e  # Exit on any error

# ============================================================================
# CONFIGURATION & VALIDATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Script is at: {root}/lambda_deployment/screening/build_lambda.sh
# Going up 2 levels (../..) gets us to project root
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"
AGENT_NAME="screening"
PYTHON_VERSION="3.12"
VENV_DIR="$BUILD_DIR/venv"
REQUIREMENTS_FILE="$BUILD_DIR/requirements-${AGENT_NAME}.txt"
DEPLOYMENT_ZIP="$BUILD_DIR/${AGENT_NAME}.zip"

echo "════════════════════════════════════════════════════════════════════════════════"
echo "🔧 Lambda Deployment Package Builder: $AGENT_NAME Agent"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Project Root:      $PROJECT_ROOT"
echo "Build Directory:   $BUILD_DIR"
echo "Python Version:    $PYTHON_VERSION"
echo "Venv:              $VENV_DIR"
echo ""

# ============================================================================
# STEP 1: VALIDATE PREREQUISITES
# ============================================================================

echo "📋 Step 1: Validating prerequisites..."

# Check required directories exist
for dir in "$PROJECT_ROOT/agents/$AGENT_NAME" "$PROJECT_ROOT/agents/shared" "$PROJECT_ROOT/contracts"; do
    if [ ! -d "$dir" ]; then
        echo "❌ ERROR: Directory not found: $dir"
        exit 1
    fi
done

if ! command -v python$PYTHON_VERSION &> /dev/null; then
    if ! command -v python3 &> /dev/null; then
        echo "❌ ERROR: Python 3.12+ not found"
        exit 1
    fi
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python$PYTHON_VERSION"
fi

echo "✅ All prerequisites validated"
echo "   Using Python: $PYTHON_CMD ($($PYTHON_CMD --version))"
echo ""

# ============================================================================
# STEP 2: CREATE OR VERIFY VENV
# ============================================================================

echo "🐍 Step 2: Setting up Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo "   ✓ Virtual environment already exists"
    source "$VENV_DIR/bin/activate"
else
    echo "   Creating new virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    echo "✅ Virtual environment created"
fi

if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ ERROR: Failed to activate virtual environment"
    exit 1
fi

echo "   Active venv: $VIRTUAL_ENV"
echo "   Python: $(python --version)"
echo ""

# ============================================================================
# STEP 3: GENERATE/VERIFY REQUIREMENTS FILE
# ============================================================================

echo "📦 Step 3: Preparing runtime dependencies..."

if [ ! -f "$REQUIREMENTS_FILE" ] || [ ! -s "$REQUIREMENTS_FILE" ]; then
    echo "   Creating requirements file..."
    cat > "$REQUIREMENTS_FILE" << 'EOF'
# Screening Agent - Runtime Dependencies
# Full agent dependencies including Strands AI framework and LLM support

# AWS SDK
boto3>=1.42.43
botocore>=1.42.24

# Strands AI Framework (Agent Runtime)
strands-agents>=1.25.0
strands-agents-tools>=0.2.19

# Data validation
pydantic>=2.12.5
pydantic-settings>=2.12.0

# Structured logging
structlog>=25.5.0
python-json-logger>=4.0.0

# Date/time handling
python-dateutil>=2.9.0.post0

# Retry logic (used in agent tools and LLM calls)
tenacity>=9.1.3

# JSON Schema validation (for contracts)
jsonschema>=4.26.0
EOF
    echo "   ✓ Requirements file created"
else
    echo "   ✓ Using existing requirements file"
fi

echo ""
echo "   Dependencies:"
grep -v "^#" "$REQUIREMENTS_FILE" | grep -v "^$" | sed 's/^/      - /'
echo ""

# ============================================================================
# STEP 4: INSTALL DEPENDENCIES
# ============================================================================

echo "⬇️  Step 4: Installing runtime dependencies..."

pip install --quiet --upgrade pip setuptools wheel
pip install --quiet -r "$REQUIREMENTS_FILE"

if [ $? -ne 0 ]; then
    echo "❌ ERROR: Failed to install dependencies"
    exit 1
fi

echo "✅ Dependencies installed successfully"
echo ""

# ============================================================================
# STEP 5: CLEAN BUILD DIRECTORY
# ============================================================================

echo "🧹 Step 5: Cleaning build directory..."

find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$BUILD_DIR" -type f -name ".DS_Store" -delete 2>/dev/null || true
rm -f "$DEPLOYMENT_ZIP"

echo "✅ Build directory cleaned"
echo ""

# ============================================================================
# STEP 6: COPY AGENT CODE (with proper package structure)
# ============================================================================

echo "📋 Step 6: Copying Agent source code..."

# Remove old copies if they exist (clean slate)
rm -rf "$BUILD_DIR/agents" "$BUILD_DIR/contracts" 2>/dev/null || true

# Create agents directory structure
mkdir -p "$BUILD_DIR/agents/$AGENT_NAME"

# Copy agents/__init__.py
cp "$PROJECT_ROOT/agents/__init__.py" "$BUILD_DIR/agents/" 2>/dev/null || touch "$BUILD_DIR/agents/__init__.py"

# Copy screening agent module (excluding __pycache__)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' --exclude='tests' \
    "$PROJECT_ROOT/agents/$AGENT_NAME/" "$BUILD_DIR/agents/$AGENT_NAME/"

FILE_COUNT=$(find "$BUILD_DIR/agents/$AGENT_NAME" -type f -name "*.py" | wc -l)
echo "   ✓ Copied $FILE_COUNT Python files from agents/$AGENT_NAME"

# Verify critical agent files
CRITICAL_AGENT_FILES=(
    "agents/$AGENT_NAME/__init__.py"
    "agents/$AGENT_NAME/agent.py"
    "agents/$AGENT_NAME/config.py"
    "agents/$AGENT_NAME/models.py"
    "agents/$AGENT_NAME/prompts.py"
    "agents/$AGENT_NAME/tools.py"
    "agents/$AGENT_NAME/llm_tools.py"
    "agents/$AGENT_NAME/llm_prompts.py"
)

for file in "${CRITICAL_AGENT_FILES[@]}"; do
    if [ ! -f "$BUILD_DIR/$file" ]; then
        echo "❌ ERROR: Missing critical file: $file"
        exit 1
    fi
done

echo "✅ Agent code copied and validated"
echo ""

# ============================================================================
# STEP 7: COPY AGENTS/SHARED (all shared utilities)
# ============================================================================

echo "📋 Step 7: Copying agents/shared code..."

# Copy entire agents/shared directory (rsync excludes __pycache__ and .pyc)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' --exclude='tests' \
    "$PROJECT_ROOT/agents/shared/" "$BUILD_DIR/agents/shared/"

SHARED_FILES=$(find "$BUILD_DIR/agents/shared" -type f -name "*.py" | wc -l)
echo "   ✓ Copied $SHARED_FILES Python files from agents/shared"

# Verify critical shared files
CRITICAL_SHARED=(
    "agents/shared/__init__.py"
    "agents/shared/config.py"
    "agents/shared/exceptions.py"
    "agents/shared/state_machine.py"
    "agents/shared/models/__init__.py"
    "agents/shared/models/dynamo.py"
    "agents/shared/models/events.py"
    "agents/shared/models/email_thread.py"
    "agents/shared/tools/__init__.py"
    "agents/shared/tools/dynamodb.py"
    "agents/shared/tools/email.py"
    "agents/shared/tools/email_thread.py"
    "agents/shared/tools/eventbridge.py"
    "agents/shared/tools/s3.py"
    "agents/shared/llm/__init__.py"
    "agents/shared/llm/bedrock_client.py"
    "agents/shared/llm/config.py"
    "agents/shared/llm/schemas.py"
)

for file in "${CRITICAL_SHARED[@]}"; do
    if [ ! -f "$BUILD_DIR/$file" ]; then
        echo "❌ ERROR: Missing critical file: $file"
        exit 1
    fi
done

echo "✅ agents/shared code copied and validated"
echo ""

# ============================================================================
# STEP 8: COPY CONTRACTS (all JSON schemas)
# ============================================================================

echo "📋 Step 8: Copying contract files..."

# Copy entire contracts directory
rsync -a --exclude='__pycache__' --exclude='.DS_Store' \
    "$PROJECT_ROOT/contracts/" "$BUILD_DIR/contracts/"

CONTRACTS_COUNT=$(find "$BUILD_DIR/contracts" -type f -name "*.json" | wc -l)
echo "   ✓ Copied $CONTRACTS_COUNT JSON schema files"

# Verify critical contracts
for file in events.json state_machine.json requirements_schema.json document_types.json; do
    if [ ! -f "$BUILD_DIR/contracts/$file" ]; then
        echo "❌ ERROR: Missing critical contract: $file"
        exit 1
    fi
done

echo "✅ Contracts copied and validated"
echo ""

# ============================================================================
# STEP 9: CREATE LAMBDA HANDLER WRAPPER
# ============================================================================

echo "📋 Step 9: Creating Lambda handler wrapper..."

cat > "$BUILD_DIR/lambda_handler.py" << 'EOF'
"""
Lambda Handler Wrapper for Screening Agent

This module provides the AWS Lambda entry point for the Screening agent.
It wraps the agent's event handler functions for Lambda execution.
"""

import json
import structlog
from typing import Any

from agents.screening.agent import (
    handle_provider_response_received,
    handle_document_processed,
)

log = structlog.get_logger()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for Screening agent.
    
    Handles EventBridge events:
    - ProviderResponseReceived: Classify and evaluate provider email responses
    - DocumentProcessed: Evaluate processed documents (insurance, etc.)
    
    Args:
        event: EventBridge event (or direct invocation payload)
        context: Lambda context
        
    Returns:
        Dict with statusCode and body
    """
    detail_type = event.get("detail-type", "ProviderResponseReceived")
    
    log.info(
        "screening_lambda_invoked",
        event_source=event.get("source"),
        detail_type=detail_type,
    )
    
    try:
        detail = event.get("detail", event)
        
        # Route to appropriate handler based on event type
        if detail_type == "DocumentProcessed":
            result = handle_document_processed(detail_type, detail)
        else:
            # Default to ProviderResponseReceived
            result = handle_provider_response_received(detail_type, detail)
        
        log.info(
            "screening_lambda_success",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            decision=result.decision.value if result.decision else None,
            reasoning=result.reasoning,
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "campaign_id": result.campaign_id,
                "provider_id": result.provider_id,
                "decision": result.decision.value if result.decision else None,
                "reasoning": result.reasoning,
                "next_action": result.next_action,
                "equipment_confirmed": result.equipment_confirmed,
                "equipment_missing": result.equipment_missing,
                "documents_valid": result.documents_valid,
            }),
        }
        
    except Exception as e:
        log.error(
            "screening_lambda_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        
        return {
            "statusCode": 500,
            "body": json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }),
        }
EOF

echo "   ✓ Created lambda_handler.py"
echo "✅ Lambda handler wrapper created"
echo ""

# ============================================================================
# STEP 10: FINAL CLEANUP
# ============================================================================

echo "🧹 Step 10: Final cleanup..."

# Extra safety: remove any __pycache__ that might have slipped through
find "$BUILD_DIR/agents" "$BUILD_DIR/contracts" \
    -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/agents" "$BUILD_DIR/contracts" \
    -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".DS_Store" \) -delete 2>/dev/null || true

echo "✅ Cleanup complete"
echo ""

# ============================================================================
# STEP 11: VERIFY PACKAGE STRUCTURE
# ============================================================================

echo "🔍 Step 11: Verifying package structure..."

for dir in "agents/$AGENT_NAME" agents/shared/tools agents/shared/models agents/shared/llm contracts; do
    if [ -d "$BUILD_DIR/$dir" ]; then
        FILE_COUNT=$(find "$BUILD_DIR/$dir" -type f | wc -l)
        echo "   ✓ $dir ($FILE_COUNT files)"
    else
        echo "   ✗ $dir (MISSING!)"
    fi
done

if [ -f "$BUILD_DIR/lambda_handler.py" ]; then
    echo "   ✓ lambda_handler.py"
else
    echo "   ✗ lambda_handler.py (MISSING!)"
fi

echo ""
echo "✅ Package structure verified"
echo ""

# ============================================================================
# STEP 12: CREATE DEPLOYMENT ZIP
# ============================================================================

echo "📦 Step 12: Creating Lambda deployment ZIP..."

cd "$BUILD_DIR"

# Create ZIP with only the code directories (not venv, scripts, etc.)
zip -r9 "$DEPLOYMENT_ZIP" \
    agents contracts lambda_handler.py \
    -x "*/__pycache__/*" "*.pyc" "*.pyo" ".DS_Store" \
    > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo "❌ ERROR: Failed to create ZIP"
    exit 1
fi

echo "   ✓ Added source code to ZIP"

# Add venv site-packages (dependencies)
SITE_PACKAGES=$(find "$VENV_DIR/lib" -maxdepth 2 -type d -name "site-packages" | head -1)
if [ -z "$SITE_PACKAGES" ]; then
    echo "❌ ERROR: site-packages not found"
    exit 1
fi

cd "$SITE_PACKAGES"
zip -r9 "$DEPLOYMENT_ZIP" . \
    -x "pip/*" "pip-*/*" "_pip*" \
    -x "setuptools/*" "setuptools-*/*" "pkg_resources/*" \
    -x "wheel/*" "wheel-*/*" \
    -x "*__pycache__*" "*.pyc" "*.pyo" \
    -x "*.dist-info/RECORD" "*.dist-info/INSTALLER" \
    -x ".DS_Store" \
    > /dev/null 2>&1

echo "   ✓ Added Python dependencies to ZIP"

cd "$BUILD_DIR"

if [ ! -f "$DEPLOYMENT_ZIP" ]; then
    echo "❌ ERROR: ZIP file not created"
    exit 1
fi

ZIP_SIZE=$(ls -lh "$DEPLOYMENT_ZIP" | awk '{print $5}')
ZIP_SIZE_BYTES=$(ls -l "$DEPLOYMENT_ZIP" | awk '{print $5}')

# Lambda uncompressed limit is 250MB, compressed limit is 50MB
if [ "$ZIP_SIZE_BYTES" -gt 52428800 ]; then
    echo "⚠️  WARNING: ZIP exceeds 50MB Lambda limit ($ZIP_SIZE)"
    echo "   Consider using Lambda Layers for dependencies"
fi

echo "✅ Deployment ZIP created"
echo "   Location: $DEPLOYMENT_ZIP"
echo "   Size: $ZIP_SIZE"
echo ""

# ============================================================================
# STEP 13: VALIDATE ZIP CONTENTS
# ============================================================================

echo "🔎 Step 13: Validating ZIP contents..."

CRITICAL_IN_ZIP=(
    "lambda_handler.py"
    "agents/$AGENT_NAME/agent.py"
    "agents/$AGENT_NAME/__init__.py"
    "agents/$AGENT_NAME/tools.py"
    "agents/$AGENT_NAME/models.py"
    "agents/$AGENT_NAME/config.py"
    "agents/$AGENT_NAME/llm_tools.py"
    "agents/$AGENT_NAME/llm_prompts.py"
    "agents/shared/config.py"
    "agents/shared/__init__.py"
    "agents/shared/tools/dynamodb.py"
    "agents/shared/tools/email_thread.py"
    "agents/shared/tools/eventbridge.py"
    "agents/shared/tools/s3.py"
    "agents/shared/tools/__init__.py"
    "agents/shared/models/events.py"
    "agents/shared/models/email_thread.py"
    "agents/shared/models/__init__.py"
    "agents/shared/llm/__init__.py"
    "agents/shared/llm/bedrock_client.py"
    "agents/shared/llm/schemas.py"
    "contracts/events.json"
    "contracts/state_machine.json"
    "contracts/requirements_schema.json"
    "contracts/document_types.json"
)

MISSING_COUNT=0
for file in "${CRITICAL_IN_ZIP[@]}"; do
    if ! unzip -l "$DEPLOYMENT_ZIP" | grep -q "$file"; then
        echo "   ❌ Missing: $file"
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi
done

# Check for critical dependencies
if ! unzip -l "$DEPLOYMENT_ZIP" | grep -q "strands"; then
    echo "   ⚠️  Warning: strands package may not be included"
fi

if [ $MISSING_COUNT -gt 0 ]; then
    echo "❌ ERROR: $MISSING_COUNT files missing from ZIP"
    exit 1
fi

echo "✅ ZIP validation complete"
echo ""

# ============================================================================
# SUMMARY
# ============================================================================

echo "════════════════════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT PACKAGE READY FOR AWS LAMBDA"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📦 Package: $DEPLOYMENT_ZIP"
echo "   Size: $ZIP_SIZE"
echo ""
echo "📋 Contents:"
echo "   ✓ Screening Agent (agent, tools, models, config, llm_tools)"
echo "   ✓ Shared Libraries (config, models, tools, llm, state_machine)"
echo "   ✓ Contracts (event schemas, state_machine, requirements, document_types)"
echo "   ✓ Lambda Handler Wrapper (lambda_handler.py)"
echo "   ✓ Dependencies (strands-agents, boto3, pydantic, structlog, tenacity)"
echo ""
echo "🚀 Deploy Command:"
echo "   aws lambda create-function --function-name screening-agent \\"
echo "     --runtime python3.12 \\"
echo "     --handler lambda_handler.lambda_handler \\"
echo "     --zip-file fileb://$DEPLOYMENT_ZIP \\"
echo "     --role arn:aws:iam::ACCOUNT_ID:role/RecruitmentLambdaExecutionRole \\"
echo "     --timeout 120 \\"
echo "     --memory-size 512"
echo ""
echo "📡 EventBridge Rules:"
echo "   # ProviderResponseReceived → Screening Agent"
echo "   aws events put-rule --name screening-response-trigger \\"
echo "     --event-bus-name recruitment-events-poc \\"
echo "     --event-pattern '{\"detail-type\": [\"ProviderResponseReceived\"]}'"
echo ""
echo "   # DocumentProcessed → Screening Agent"
echo "   aws events put-rule --name screening-document-trigger \\"
echo "     --event-bus-name recruitment-events-poc \\"
echo "     --event-pattern '{\"detail-type\": [\"DocumentProcessed\"]}'"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"

