#!/bin/bash

################################################################################
# Lambda Deployment Package Builder: process_inbound_email
# 
# This script automates the complete process of packaging the process_inbound_email
# Lambda function for AWS deployment. It:
# 1. Creates/uses Python 3.12 venv (AWS supported version)
# 2. Installs runtime dependencies
# 3. Copies source code from agents/, lambdas/, and contracts/
# 4. Cleans up unnecessary files
# 5. Creates AWS Lambda deployment ZIP
#
# Usage: ./build_lambda.sh
# Run from: {root}/lambda_deployment/process_inbound_email/
################################################################################

set -e  # Exit on any error

# ============================================================================
# CONFIGURATION & VALIDATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Script is at: {root}/lambda_deployment/process_inbound_email/build_lambda.sh
# Going up 2 levels (../..) gets us to project root
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"
LAMBDA_NAME="process_inbound_email"
PYTHON_VERSION="3.12"
VENV_DIR="$BUILD_DIR/venv"
REQUIREMENTS_FILE="$BUILD_DIR/requirements-${LAMBDA_NAME}.txt"
DEPLOYMENT_ZIP="$BUILD_DIR/${LAMBDA_NAME}.zip"

echo "════════════════════════════════════════════════════════════════════════════════"
echo "🔧 Lambda Deployment Package Builder: $LAMBDA_NAME"
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

for dir in "$PROJECT_ROOT/lambdas" "$PROJECT_ROOT/agents/shared" "$PROJECT_ROOT/contracts" "$PROJECT_ROOT/lambdas/$LAMBDA_NAME"; do
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
# Process Inbound Email Lambda - Runtime Dependencies
# Optimized: Only runtime deps needed (no Strands, Jinja2, testing tools)

boto3>=1.42.43
botocore>=1.42.24
pydantic>=2.12.5
pydantic-settings>=2.12.0
structlog>=25.5.0
python-json-logger>=4.0.0
python-dateutil>=2.9.0.post0
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
# STEP 6: COPY LAMBDA CODE (with proper package structure)
# ============================================================================

echo "📋 Step 6: Copying Lambda source code..."

# Remove old copies if they exist (clean slate)
rm -rf "$BUILD_DIR/lambdas" "$BUILD_DIR/agents" "$BUILD_DIR/contracts" 2>/dev/null || true

# Copy lambdas directory structure (only process_inbound_email and parent __init__.py)
mkdir -p "$BUILD_DIR/lambdas/$LAMBDA_NAME"

# Copy lambdas/__init__.py (already exists in source)
cp "$PROJECT_ROOT/lambdas/__init__.py" "$BUILD_DIR/lambdas/" 2>/dev/null || touch "$BUILD_DIR/lambdas/__init__.py"

# Copy lambda module files (excluding __pycache__)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    "$PROJECT_ROOT/lambdas/$LAMBDA_NAME/" "$BUILD_DIR/lambdas/$LAMBDA_NAME/"

FILE_COUNT=$(find "$BUILD_DIR/lambdas/$LAMBDA_NAME" -type f -name "*.py" | wc -l)
echo "   ✓ Copied $FILE_COUNT Python files from lambdas/$LAMBDA_NAME"

# Verify critical files
for file in handler.py email_parser.py attachment_handler.py __init__.py; do
    if [ ! -f "$BUILD_DIR/lambdas/$LAMBDA_NAME/$file" ]; then
        echo "❌ ERROR: Missing critical file: lambdas/$LAMBDA_NAME/$file"
        exit 1
    fi
done

echo "✅ Lambda code copied and validated"
echo ""

# ============================================================================
# STEP 7: COPY AGENTS/SHARED (preserving existing structure)
# ============================================================================

echo "📋 Step 7: Copying agents/shared code..."

# Create agents directory and copy __init__.py from source
mkdir -p "$BUILD_DIR/agents"
cp "$PROJECT_ROOT/agents/__init__.py" "$BUILD_DIR/agents/" 2>/dev/null || touch "$BUILD_DIR/agents/__init__.py"

# Copy entire agents/shared directory (rsync excludes __pycache__ and .pyc)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    "$PROJECT_ROOT/agents/shared/" "$BUILD_DIR/agents/shared/"

SHARED_FILES=$(find "$BUILD_DIR/agents/shared" -type f -name "*.py" | wc -l)
echo "   ✓ Copied $SHARED_FILES Python files from agents/shared"

# Verify critical files (all should exist since we copied the whole directory)
CRITICAL_SHARED=(
    "agents/shared/__init__.py"
    "agents/shared/config.py"
    "agents/shared/exceptions.py"
    "agents/shared/state_machine.py"
    "agents/shared/models/__init__.py"
    "agents/shared/models/dynamo.py"
    "agents/shared/models/email_thread.py"
    "agents/shared/tools/__init__.py"
    "agents/shared/tools/dynamodb.py"
    "agents/shared/tools/email_thread.py"
    "agents/shared/llm/__init__.py"
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
for file in events.json state_machine.json email_config.json; do
    if [ ! -f "$BUILD_DIR/contracts/$file" ]; then
        echo "❌ ERROR: Missing critical contract: $file"
        exit 1
    fi
done

echo "✅ Contracts copied and validated"
echo ""

# ============================================================================
# STEP 9: FINAL CLEANUP (remove any stray cache files)
# ============================================================================

echo "🧹 Step 9: Final cleanup..."

# Extra safety: remove any __pycache__ that might have slipped through
find "$BUILD_DIR/lambdas" "$BUILD_DIR/agents" "$BUILD_DIR/contracts" \
    -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/lambdas" "$BUILD_DIR/agents" "$BUILD_DIR/contracts" \
    -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".DS_Store" \) -delete 2>/dev/null || true

echo "✅ Cleanup complete"
echo ""

# ============================================================================
# STEP 10: VERIFY PACKAGE STRUCTURE
# ============================================================================

echo "🔍 Step 10: Verifying package structure..."

for dir in lambdas/process_inbound_email agents/shared/tools agents/shared/models contracts; do
    if [ -d "$BUILD_DIR/$dir" ]; then
        FILE_COUNT=$(find "$BUILD_DIR/$dir" -type f | wc -l)
        echo "   ✓ $dir ($FILE_COUNT files)"
    else
        echo "   ✗ $dir (MISSING!)"
    fi
done

echo ""
echo "✅ Package structure verified"
echo ""

# ============================================================================
# STEP 11: CREATE DEPLOYMENT ZIP
# ============================================================================

echo "📦 Step 11: Creating Lambda deployment ZIP..."

cd "$BUILD_DIR"

# Create ZIP with only the code directories (not venv, scripts, etc.)
zip -r9 "$DEPLOYMENT_ZIP" \
    lambdas agents contracts \
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

if [ "$ZIP_SIZE_BYTES" -gt 52428800 ]; then
    echo "❌ ERROR: ZIP exceeds 50MB limit ($ZIP_SIZE)"
    exit 1
fi

echo "✅ Deployment ZIP created"
echo "   Location: $DEPLOYMENT_ZIP"
echo "   Size: $ZIP_SIZE"
echo ""

# ============================================================================
# STEP 12: VALIDATE ZIP
# ============================================================================

echo "🔎 Step 12: Validating ZIP contents..."

CRITICAL_IN_ZIP=(
    "lambdas/process_inbound_email/handler.py"
    "lambdas/process_inbound_email/__init__.py"
    "agents/shared/config.py"
    "agents/shared/__init__.py"
    "agents/shared/tools/dynamodb.py"
    "agents/shared/tools/__init__.py"
    "agents/shared/models/email_thread.py"
    "agents/shared/models/__init__.py"
    "agents/shared/llm/__init__.py"
    "contracts/events.json"
    "contracts/state_machine.json"
)

MISSING_COUNT=0
for file in "${CRITICAL_IN_ZIP[@]}"; do
    if ! unzip -l "$DEPLOYMENT_ZIP" | grep -q "$file"; then
        echo "   ❌ Missing: $file"
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi
done

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
echo "   ✓ Lambda Code (handler, parser, attachment handler)"
echo "   ✓ Shared Libraries (config, models, tools, llm, state machine)"
echo "   ✓ Contracts (event schemas, state_machine, email_config)"
echo "   ✓ Dependencies (boto3, pydantic, structlog, python-dateutil)"
echo ""
echo "🚀 Deploy Command:"
echo "   aws lambda create-function --function-name process-inbound-email \\"
echo "     --runtime python3.12 \\"
echo "     --handler lambdas.process_inbound_email.handler.lambda_handler \\"
echo "     --zip-file fileb://$DEPLOYMENT_ZIP \\"
echo "     --role arn:aws:iam::ACCOUNT_ID:role/LambdaExecutionRole"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
