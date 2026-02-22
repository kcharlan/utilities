import json
from abc import ABC, abstractmethod
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from llm_proxy.auth import decode_credentials, extract_authorization
from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelObject,
)


class ProviderAdapter(ABC):

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """URL path prefix and unique identifier, e.g. 't3chat'.
        The adapter will be mounted at /{provider_id}/v1/"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'T3 Chat'."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Called once at startup. Use for model discovery, connection
        setup, or any async initialization."""
        ...

    @abstractmethod
    def get_models(self) -> list[ModelObject]:
        """Return list of models in OpenAI ModelObject format."""
        ...

    @abstractmethod
    def get_opencode_model_config(self) -> list[dict]:
        """Return list of model dicts in OpenCode config format."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion."""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Execute a streaming chat completion."""
        ...

    def create_router(self) -> APIRouter:
        """Creates the FastAPI router with /v1/chat/completions and /v1/models."""
        router = APIRouter()
        adapter = self

        @router.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            body = await request.json()
            chat_request = ChatCompletionRequest(**body)

            auth_header = extract_authorization(request)
            credentials = decode_credentials(auth_header)

            if chat_request.stream:

                async def event_stream():
                    async for chunk in adapter.chat_completion_stream(
                        chat_request, credentials
                    ):
                        yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    event_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            else:
                response = await adapter.chat_completion(chat_request, credentials)
                return response

        @router.get("/v1/models")
        async def list_models():
            models = adapter.get_models()
            return ModelListResponse(data=models)

        return router
