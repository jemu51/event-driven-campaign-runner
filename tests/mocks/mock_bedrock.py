"""
Mock Bedrock LLM Client for Testing

Provides a mock implementation of the BedrockLLMClient that returns
predictable, deterministic responses for testing without AWS.

Usage:
    from tests.mocks.mock_bedrock import MockBedrockLLMClient
    
    client = MockBedrockLLMClient()
    client.set_response(EmailGenerationOutput(...))
    result = client.invoke_structured(prompt, EmailGenerationOutput)
"""

from typing import Type, TypeVar, Any
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class MockLLMError(Exception):
    """Mock error to simulate LLM failures."""
    pass


class MockBedrockLLMClient:
    """
    Mock Bedrock client for testing without AWS.
    
    Features:
    - Returns preconfigured responses
    - Records all invocations for verification
    - Can simulate errors
    - Supports multiple response types
    """
    
    def __init__(self):
        """Initialize mock client with empty state."""
        self._responses: dict[Type[BaseModel], BaseModel] = {}
        self._invocations: list[dict[str, Any]] = []
        self._error: Exception | None = None
        self._call_count: int = 0
        
    def set_response(self, response: BaseModel) -> None:
        """
        Set the response to return for a given output type.
        
        Args:
            response: The response object to return when invoke_structured
                      is called with the matching output model type.
        """
        self._responses[type(response)] = response
        
    def set_responses(self, responses: list[BaseModel]) -> None:
        """
        Set multiple responses for different output types.
        
        Args:
            responses: List of response objects to configure
        """
        for response in responses:
            self.set_response(response)
            
    def set_error(self, error: Exception) -> None:
        """
        Configure the mock to raise an error on next invocation.
        
        Args:
            error: The exception to raise
        """
        self._error = error
        
    def clear_error(self) -> None:
        """Clear any configured error."""
        self._error = None
        
    def reset(self) -> None:
        """Reset all state (responses, invocations, errors)."""
        self._responses.clear()
        self._invocations.clear()
        self._error = None
        self._call_count = 0
        
    @property
    def call_count(self) -> int:
        """Get the number of times invoke_structured was called."""
        return self._call_count
        
    @property
    def invocations(self) -> list[dict[str, Any]]:
        """Get list of all invocations for verification."""
        return self._invocations.copy()
        
    @property
    def last_invocation(self) -> dict[str, Any] | None:
        """Get the most recent invocation, or None if no invocations."""
        return self._invocations[-1] if self._invocations else None
        
    def invoke_structured(
        self,
        prompt: str,
        output_model: Type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """
        Mock invoke_structured that returns preconfigured responses.
        
        Args:
            prompt: The user prompt (recorded for verification)
            output_model: Pydantic model class for response type
            system_prompt: Optional system prompt (recorded)
            temperature: Optional temperature override (recorded)
            
        Returns:
            The preconfigured response for the output_model type
            
        Raises:
            MockLLMError: If configured to raise an error
            ValueError: If no response is configured for the output type
        """
        self._call_count += 1
        
        # Record the invocation
        invocation = {
            "prompt": prompt,
            "output_model": output_model.__name__,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "call_number": self._call_count,
        }
        self._invocations.append(invocation)
        
        # Raise error if configured
        if self._error is not None:
            error = self._error
            self._error = None  # Only raise once
            raise error
            
        # Return configured response
        if output_model in self._responses:
            return self._responses[output_model]  # type: ignore
            
        # Check if we have a response of the matching type
        for response_type, response in self._responses.items():
            if response_type == output_model:
                return response  # type: ignore
                
        raise ValueError(
            f"No mock response configured for {output_model.__name__}. "
            f"Use client.set_response() to configure a response."
        )
        
    def assert_called_once(self) -> None:
        """Assert that invoke_structured was called exactly once."""
        assert self._call_count == 1, (
            f"Expected 1 call, got {self._call_count}"
        )
        
    def assert_called(self) -> None:
        """Assert that invoke_structured was called at least once."""
        assert self._call_count > 0, "Expected at least 1 call, got 0"
        
    def assert_not_called(self) -> None:
        """Assert that invoke_structured was not called."""
        assert self._call_count == 0, (
            f"Expected 0 calls, got {self._call_count}"
        )
        
    def assert_prompt_contains(self, substring: str) -> None:
        """Assert that the last prompt contained a substring."""
        assert self._invocations, "No invocations recorded"
        last_prompt = self._invocations[-1]["prompt"]
        assert substring in last_prompt, (
            f"Expected prompt to contain '{substring}', got: {last_prompt[:200]}..."
        )


# Convenience function for creating a pre-configured mock
def create_mock_client(**responses) -> MockBedrockLLMClient:
    """
    Create a mock client with responses pre-configured.
    
    Args:
        **responses: Keyword arguments mapping output types to responses
        
    Returns:
        Configured MockBedrockLLMClient
        
    Example:
        client = create_mock_client(
            email=EmailGenerationOutput(subject="Test", ...),
            classification=ResponseClassificationOutput(intent="positive", ...),
        )
    """
    client = MockBedrockLLMClient()
    for response in responses.values():
        if isinstance(response, BaseModel):
            client.set_response(response)
    return client
