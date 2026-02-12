"""
Bedrock LLM Client

Provides structured output from Claude via AWS Bedrock.
Uses Strands Agents SDK for model invocation with Pydantic validation.
"""

import json
from functools import lru_cache
from typing import Type, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from strands import Agent
from strands.models import BedrockModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from agents.shared.llm.config import LLMSettings, get_llm_settings


log = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


class LLMInvocationError(Exception):
    """Raised when LLM invocation fails after retries."""
    
    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class LLMParsingError(Exception):
    """Raised when LLM output cannot be parsed into the expected schema."""
    
    def __init__(self, message: str, raw_output: str | None = None):
        super().__init__(message)
        self.raw_output = raw_output


class BedrockLLMClient:
    """
    Wrapper for AWS Bedrock Claude invocation with structured output.
    
    Features:
    - Structured output via Pydantic models
    - Automatic retry with exponential backoff
    - Comprehensive error handling
    - Configurable model parameters
    
    Usage:
        client = BedrockLLMClient()
        result = client.invoke_structured(
            prompt="Classify this email response...",
            output_schema=ResponseClassificationOutput,
            system_prompt="You are an email classifier...",
        )
    """
    
    def __init__(self, settings: LLMSettings | None = None):
        """
        Initialize the Bedrock LLM client.
        
        Args:
            settings: LLM settings instance. If None, uses the cached singleton.
        """
        self._settings = settings or get_llm_settings()
        self._agent: Agent | None = None
        self._model: BedrockModel | None = None
    
    @property
    def settings(self) -> LLMSettings:
        """Get the LLM settings."""
        return self._settings
    
    def _get_model(self) -> BedrockModel:
        """
        Get or create the Bedrock model instance.
        
        Returns:
            Configured BedrockModel instance
        """
        if self._model is None:
            model_kwargs = {
                "model_id": self._settings.bedrock_model_id,
            }
            
            # Add optional endpoint URL for testing/VPC
            if self._settings.bedrock_endpoint_url:
                model_kwargs["endpoint_url"] = self._settings.bedrock_endpoint_url
            
            self._model = BedrockModel(**model_kwargs)
            
            log.debug(
                "bedrock_model_initialized",
                model_id=self._settings.bedrock_model_id,
                region=self._settings.bedrock_region,
            )
        
        return self._model
    
    def _get_agent(self, system_prompt: str | None = None) -> Agent:
        """
        Get or create the Strands Agent instance.
        
        Args:
            system_prompt: Optional system prompt for the agent
            
        Returns:
            Configured Agent instance
        """
        model = self._get_model()
        
        agent_kwargs = {
            "model": model,
        }
        
        if system_prompt:
            agent_kwargs["system_prompt"] = system_prompt
        
        return Agent(**agent_kwargs)
    
    def _build_structured_prompt(self, prompt: str, output_schema: Type[T]) -> str:
        """
        Build a prompt that instructs the LLM to output structured JSON.
        
        Args:
            prompt: User prompt
            output_schema: Pydantic model class for the expected output
            
        Returns:
            Enhanced prompt with JSON output instructions
        """
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        
        return f"""{prompt}

IMPORTANT: You must respond with valid JSON that matches this schema:
```json
{schema_json}
```

Respond ONLY with the JSON object, no additional text or markdown."""

    @staticmethod
    def _sanitize_json_strings(raw: str) -> str:
        """
        Escape control characters inside JSON double-quoted string values.
        LLMs sometimes emit literal newlines inside strings, which is invalid JSON.
        """
        result: list[str] = []
        i = 0
        in_string = False
        escape_next = False
        while i < len(raw):
            c = raw[i]
            if escape_next:
                result.append(c)
                escape_next = False
                i += 1
                continue
            if c == "\\" and in_string:
                result.append(c)
                escape_next = True
                i += 1
                continue
            if c == '"':
                result.append(c)
                in_string = not in_string
                i += 1
                continue
            if in_string and ord(c) < 32:
                # Control character: escape for JSON
                if c == "\n":
                    result.append("\\n")
                elif c == "\r":
                    result.append("\\r")
                elif c == "\t":
                    result.append("\\t")
                else:
                    result.append(f"\\u{ord(c):04x}")
                i += 1
                continue
            result.append(c)
            i += 1
        return "".join(result)

    def _parse_response(self, response: str, output_schema: Type[T]) -> T:
        """
        Parse LLM response into the expected Pydantic model.
        
        Args:
            response: Raw LLM response text
            output_schema: Pydantic model class to parse into
            
        Returns:
            Validated Pydantic model instance
            
        Raises:
            LLMParsingError: If parsing fails
        """
        # Clean up response - remove markdown code blocks if present
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        # Escape control characters inside JSON strings (e.g. literal newlines from LLM)
        cleaned = self._sanitize_json_strings(cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error(
                "llm_json_parse_error",
                error=str(e),
                response_preview=cleaned[:200],
            )
            raise LLMParsingError(
                f"Failed to parse LLM response as JSON: {e}",
                raw_output=response,
            ) from e
        
        try:
            return output_schema.model_validate(data)
        except ValidationError as e:
            log.error(
                "llm_schema_validation_error",
                error=str(e),
                schema=output_schema.__name__,
            )
            raise LLMParsingError(
                f"LLM response does not match schema {output_schema.__name__}: {e}",
                raw_output=response,
            ) from e
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMInvocationError,)),
        reraise=True,
    )
    def invoke_structured(
        self,
        prompt: str,
        output_schema: Type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """
        Invoke Claude and parse response into a Pydantic model.
        
        Args:
            prompt: User prompt with context and instructions
            output_schema: Pydantic model class for structured output
            system_prompt: Optional system instructions
            temperature: Sampling temperature (0-1), defaults to settings
            max_tokens: Maximum response tokens, defaults to settings
            
        Returns:
            Parsed and validated Pydantic model instance
            
        Raises:
            LLMInvocationError: If the LLM call fails after retries
            LLMParsingError: If the response cannot be parsed
        """
        if not self._settings.llm_enabled:
            raise LLMInvocationError("LLM is disabled via settings")
        
        effective_temp = temperature if temperature is not None else self._settings.llm_temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._settings.llm_max_tokens
        
        log.info(
            "llm_invoke_start",
            schema=output_schema.__name__,
            temperature=effective_temp,
            max_tokens=effective_max_tokens,
        )
        
        try:
            # Build prompt with schema instructions
            structured_prompt = self._build_structured_prompt(prompt, output_schema)
            
            # Create agent with system prompt
            agent = self._get_agent(system_prompt)
            
            # Invoke the model
            response = agent(structured_prompt)
            
            # Extract text from response
            response_text = str(response)
            
            log.debug(
                "llm_raw_response",
                response_preview=response_text[:500] if len(response_text) > 500 else response_text,
            )
            
            # Parse into schema
            result = self._parse_response(response_text, output_schema)
            
            log.info(
                "llm_invoke_success",
                schema=output_schema.__name__,
            )
            
            return result
            
        except LLMParsingError:
            # Re-raise parsing errors as-is
            raise
        except Exception as e:
            log.error(
                "llm_invoke_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise LLMInvocationError(
                f"Failed to invoke LLM: {e}",
                original_error=e,
            ) from e
    
    def invoke_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """
        Invoke Claude and return raw text response.
        
        Use this for cases where structured output is not needed.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system instructions
            
        Returns:
            Raw text response from the LLM
            
        Raises:
            LLMInvocationError: If the LLM call fails
        """
        if not self._settings.llm_enabled:
            raise LLMInvocationError("LLM is disabled via settings")
        
        try:
            agent = self._get_agent(system_prompt)
            response = agent(prompt)
            return str(response)
        except Exception as e:
            log.error(
                "llm_raw_invoke_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise LLMInvocationError(
                f"Failed to invoke LLM: {e}",
                original_error=e,
            ) from e


@lru_cache(maxsize=1)
def get_llm_client() -> BedrockLLMClient:
    """
    Get cached Bedrock LLM client instance.
    
    Uses lru_cache to ensure a single client instance is reused.
    For testing, create BedrockLLMClient() directly with mock settings.
    
    Returns:
        BedrockLLMClient instance
    """
    return BedrockLLMClient()
