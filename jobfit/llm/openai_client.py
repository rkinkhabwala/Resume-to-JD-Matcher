from __future__ import annotations

from typing import Any, Protocol, cast

from openai import (
    AzureOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from pydantic import ValidationError

from jobfit.config import Settings
from jobfit.llm.protocol import ModelT, TokenUsage
from jobfit.schemas.llm import JobAnalysis, ResumeAnalysis


class LLMConfigurationError(ValueError):
    pass


class LLMResponseError(RuntimeError):
    pass


class LLMRefusalError(LLMResponseError):
    pass


class _ResponsesAPI(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


class _SDKClient(Protocol):
    responses: _ResponsesAPI


class OpenAIResponsesClient:
    def __init__(
        self,
        model: str,
        *,
        supports_temperature: bool = True,
        client: _SDKClient | None = None,
    ) -> None:
        self._model = model
        self._supports_temperature = supports_temperature
        self._client = client

    def parse(
        self,
        system: str,
        user: str,
        schema: type[ModelT],
    ) -> tuple[ModelT, TokenUsage]:
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        feedback: str | None = None

        for attempt in range(2):
            request_user = user
            if feedback is not None:
                request_user = (
                    f"{user}\n\nCorrection from the previous attempt:\n{feedback}"
                )
            try:
                response = self._parse_response(system, request_user, schema)
            except (
                ContentFilterFinishReasonError,
                LengthFinishReasonError,
                ValidationError,
            ) as exc:
                if attempt == 1:
                    raise LLMResponseError(
                        "The model could not produce valid structured output after "
                        "one retry."
                    ) from exc
                feedback = _validation_feedback(exc)
                continue

            usage = _add_usage(usage, _read_usage(response))
            refusal = _read_refusal(response)
            if refusal is not None:
                if attempt == 1:
                    raise LLMRefusalError(
                        "The model refused to complete the structured extraction."
                    )
                feedback = f"The previous response was refused: {refusal}"
                continue

            parsed = getattr(response, "output_parsed", None)
            if isinstance(parsed, schema):
                return parsed, usage
            if attempt == 1:
                raise LLMResponseError(
                    "The model returned no valid structured output after one retry."
                )
            feedback = "The previous response did not contain the requested schema."

        raise LLMResponseError("The model did not return structured output.")

    def _parse_response(
        self,
        system: str,
        user: str,
        schema: type[ModelT],
    ) -> Any:
        if self._client is None:
            raise LLMConfigurationError("No OpenAI client has been configured.")
        options: dict[str, object] = {}
        if schema in (JobAnalysis, ResumeAnalysis):
            if self._supports_temperature:
                options["temperature"] = 0
            else:
                options["reasoning"] = {"effort": "low"}

        return self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
            **options,
        )


def create_llm_client(settings: Settings) -> OpenAIResponsesClient:
    if not settings.openai_api_key:
        raise LLMConfigurationError("OPENAI_API_KEY is required for LLM analysis.")

    base_url = settings.openai_base_url or None
    sdk_client: OpenAI | AzureOpenAI
    if settings.openai_api_type == "azure":
        if base_url is None:
            raise LLMConfigurationError(
                "OPENAI_BASE_URL must contain the Azure endpoint when using Azure."
            )
        sdk_client = AzureOpenAI(
            api_key=settings.openai_api_key,
            azure_endpoint=base_url,
            api_version=settings.openai_api_version,
            timeout=60,
            max_retries=3,
        )
    else:
        sdk_client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=base_url,
            timeout=60,
            max_retries=3,
        )

    return OpenAIResponsesClient(
        model=settings.llm_model,
        supports_temperature=settings.llm_supports_temperature,
        client=cast(_SDKClient, sdk_client),
    )


def _read_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def _add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
    )


def _read_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return str(getattr(content, "refusal", "refused"))
    return None


def _validation_feedback(error: Exception) -> str:
    if isinstance(error, ValidationError):
        details = error.errors(include_input=False)
        summary = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in details
        )
        return f"Structured output validation failed: {summary}"
    return (
        f"Structured output was incomplete ({type(error).__name__}). "
        "Return every required field."
    )
