# Integration Tests - Quick Reference

## 📁 Files Created

```
tests/
├── integration/
│   ├── __init__.py                      # Integration test package
│   ├── conftest.py                      # Integration test fixtures
│   └── test_campaign_flow_e2e.py        # End-to-end flow tests
└── utils/
    ├── __init__.py                      # Utils package
    └── event_generator.py               # Mock data generator
```

---

## ✅ Installation

If you haven't installed faker yet, run:

```bash
cd /Users/almansursiddiqui/dev/poc-fn-ai-agents/netdev-ai-poc-email-driven
source venv/bin/activate
pip install faker
```

Or install all dev dependencies:

```bash
pip install -e ".[dev]"
```

---

## 🧪 Running Tests

### Run All Integration Tests

```bash
pytest tests/integration/ -v -s
```

### Run Specific Test Class

```bash
# Campaign flow tests
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E -v -s

# Event-driven flow tests
pytest tests/integration/test_campaign_flow_e2e.py::TestEventDrivenFlows -v -s

# Data validation tests
pytest tests/integration/test_campaign_flow_e2e.py::TestDataValidation -v -s
```

### Run Single Test

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_single_provider_qualified_flow -v -s
```

### Filter by Markers

```bash
# Run only integration tests
pytest -m integration -v

# Skip integration tests (run only unit tests)
pytest -m "not integration" -v
```

---

## 🎲 Using the Mock Event Generator

### Basic Usage

```python
from tests.utils.event_generator import MockEventGenerator

# Create generator (with seed for reproducibility)
gen = MockEventGenerator(seed=42)

# Generate campaign event
campaign = gen.generate_new_campaign_event()
print(campaign["campaign_id"])

# Generate provider info
provider = gen.generate_provider_info(
    market="atlanta",
    has_equipment=["bucket_truck", "spectrum_analyzer"]
)

# Generate provider response
response = gen.generate_provider_response_event(
    campaign_id="campaign-001",
    provider_id=provider["provider_id"],
    provider_email=provider["email"],
    sentiment="positive",  # or "negative", "partial", "question"
    has_attachments=True
)

# Generate document processed event
doc_event = gen.generate_document_processed_event(
    campaign_id="campaign-001",
    provider_id=provider["provider_id"],
    is_valid=True
)

# Generate screening result
screening = gen.generate_screening_completed_event(
    campaign_id="campaign-001",
    provider_id=provider["provider_id"],
    result="qualified",  # or "rejected", "escalated"
    matched_equipment=["bucket_truck", "spectrum_analyzer"],
    missing_equipment=[]
)
```

### Generate Complete Campaign Flow

```python
from tests.utils.event_generator import MockEventGenerator
import json

gen = MockEventGenerator(seed=999)

# Generate full campaign with 10 providers (60% qualified)
flow = gen.generate_complete_campaign_flow(
    num_providers=10,
    qualified_ratio=0.6
)

# Access different event types
print(f"Campaign ID: {flow['campaign']['campaign_id']}")
print(f"Providers: {len(flow['providers'])}")
print(f"Messages: {len(flow['messages'])}")
print(f"Responses: {len(flow['responses'])}")
print(f"Documents: {len(flow['documents'])}")
print(f"Screenings: {len(flow['screenings'])}")

# Print full flow as JSON
print(json.dumps(flow, indent=2))
```

### Quick Random Event

```python
from tests.utils.event_generator import generate_random_event

# Generate single random event
campaign_event = generate_random_event("new_campaign")
response_event = generate_random_event(
    "provider_response",
    campaign_id="campaign-001",
    provider_id="prov-001",
    provider_email="test@example.com"
)
```

---

## 📊 Test Scenarios Covered

### 1. Single Provider Qualified Flow
**Test:** `test_single_provider_qualified_flow`

Validates complete flow:
- Campaign creation → Provider invited
- Message sent → Provider responds (positive + attachment)
- Document processed → Screening completed
- Final state: **QUALIFIED**

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_single_provider_qualified_flow -v -s
```

---

### 2. Multiple Providers with Mixed Outcomes
**Test:** `test_multiple_providers_mixed_outcomes`

Simulates realistic campaign:
- 2 providers **QUALIFIED**
- 1 provider **REJECTED** (missing equipment)
- 1 provider **WAITING_RESPONSE**
- 1 provider **ESCALATED**

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_multiple_providers_mixed_outcomes -v -s
```

---

### 3. Complete Campaign Lifecycle
**Test:** `test_complete_campaign_lifecycle`

Full campaign with 10 providers:
- Uses mock generator to create realistic data
- Verifies statistics (qualified count, rejected, etc.)
- Tests batch operations

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_complete_campaign_lifecycle -v -s
```

---

### 4. State Transition Validation
**Test:** `test_state_transition_validation`

Validates state machine:
- Tests valid transitions (INVITED → WAITING_RESPONSE → QUALIFIED)
- Ensures terminal states cannot transition

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_state_transition_validation -v -s
```

---

### 5. EventBridge Event Publishing
**Test:** `test_eventbridge_event_publishing`

Tests event infrastructure:
- Publishes events to EventBridge
- Verifies events are captured
- Validates event structure

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestEventDrivenFlows::test_eventbridge_event_publishing -v -s
```

---

### 6. Provider Response Processing
**Test:** `test_provider_response_processing`

Tests response handling:
- Provider in WAITING_RESPONSE state
- Response event generated
- Event structure validated

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestEventDrivenFlows::test_provider_response_processing -v -s
```

---

### 7. Data Generation Consistency
**Test:** `test_mock_data_generation_consistency`

Validates mock generator:
- Same seed produces same output
- Deterministic data generation

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestDataValidation::test_mock_data_generation_consistency -v -s
```

---

### 8. Data Integrity
**Test:** `test_complete_flow_data_integrity`

Validates data relationships:
- Campaign IDs match across events
- Provider IDs consistent
- Referential integrity maintained

```bash
pytest tests/integration/test_campaign_flow_e2e.py::TestDataValidation::test_complete_flow_data_integrity -v -s
```

---

## 🔧 Fixtures Available

### `integration_aws_setup` (session scope)
Complete mocked AWS environment:
- DynamoDB table with GSI
- S3 buckets
- SES verified identities
- EventBridge bus
- SNS topics

### `integration_event_collector`
Collects all EventBridge events published during test for verification.

### `clean_dynamodb_table`
Deletes all items from DynamoDB table before each test.

### `integration_campaign_id`
Generates unique campaign ID for each test.

### `integration_provider_ids`
Generates list of 5 unique provider IDs.

---

## 📝 Example Test Output

```
tests/integration/test_campaign_flow_e2e.py::TestCampaignFlowE2E::test_complete_campaign_lifecycle 

📊 Campaign Statistics:
   Total Providers: 10
   ✅ Qualified: 6
   ❌ Rejected: 3
   ⚠️  Escalated: 1
PASSED

✅ Provider prov-atl-abc12345 successfully qualified!
PASSED
```

---

## 🎯 Integration with AWS Console Testing

After running integration tests locally, you can use the generated data as templates for AWS Console testing:

1. **Copy event payloads** from test output
2. **Paste into EventBridge** console → Send custom events
3. **Monitor DynamoDB** table for state changes
4. **Check CloudWatch Logs** for agent execution

---

## 🐛 Debugging Tips

### View All Test Output
```bash
pytest tests/integration/ -v -s --tb=short
```

### Run with Coverage
```bash
pytest tests/integration/ --cov=agents --cov=lambdas --cov-report=html
```

### Stop on First Failure
```bash
pytest tests/integration/ -x
```

### Print DynamoDB Table Contents (in test)
```python
def test_something(clean_dynamodb_table):
    table = clean_dynamodb_table
    
    # ... do test operations ...
    
    # Debug: print all items
    scan = table.scan()
    for item in scan["Items"]:
        print(json.dumps(item, indent=2, default=str))
```

---

## 🚀 Next Steps

1. **Install faker** if not already done:
   ```bash
   pip install faker
   ```

2. **Run all integration tests**:
   ```bash
   pytest tests/integration/ -v -s
   ```

3. **Generate sample test data for AWS Console**:
   ```bash
   python -c "
   from tests.utils.event_generator import MockEventGenerator
   import json
   
   gen = MockEventGenerator(seed=42)
   flow = gen.generate_complete_campaign_flow(num_providers=5)
   
   # Save to file
   with open('sample_test_data.json', 'w') as f:
       json.dump(flow, f, indent=2)
   
   print('✅ Sample data saved to sample_test_data.json')
   "
   ```

4. **Use generated data in AWS Console** (see manual setup guide)

---

## 📚 Related Documentation

- [../Docs/Sample_Test_Data_&_Validation_Guide.md](../Docs/Sample_Test_Data_&_Validation_Guide.md) - AWS Console validation
- [../PROGRESS.md](../PROGRESS.md) - Project progress tracking
- [../ARCHITECHTURE.md](../ARCHITECHTURE.md) - System architecture
- [../BUILD_PLAN.md](../BUILD_PLAN.md) - Implementation phases

---

**Created:** 2026-02-07  
**Status:** ✅ Ready for testing
