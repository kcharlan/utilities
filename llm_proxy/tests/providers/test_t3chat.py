import json

import httpx
import pytest
from fastapi import HTTPException

from llm_proxy.models import ChatCompletionRequest, ChatMessage
from llm_proxy.providers.t3chat import FALLBACK_MODELS, T3ChatAdapter


@pytest.fixture
def adapter():
    a = T3ChatAdapter()
    a._models = FALLBACK_MODELS
    return a


class TestProviderIdentity:
    def test_provider_id(self):
        adapter = T3ChatAdapter()
        assert adapter.provider_id == "t3chat"

    def test_display_name(self):
        adapter = T3ChatAdapter()
        assert adapter.display_name == "T3 Chat"


class TestInitialize:
    @pytest.mark.asyncio
    async def test_successful_scrape(self, httpx_mock):
        # Build a JS chunk with >10 model IDs in an array
        model_ids = [f"model-{i}" for i in range(12)]
        id_array = ", ".join(f'"{mid}"' for mid in model_ids)
        js_content = f'let models = [{id_array}]'

        # Mock homepage with a script tag
        httpx_mock.add_response(
            url="https://t3.chat/",
            html=f'<html><script src="/_next/static/chunks/abc123.js"></script></html>',
        )
        # Mock JS chunk
        httpx_mock.add_response(
            url="https://t3.chat/_next/static/chunks/abc123.js",
            text=js_content,
        )

        adapter = T3ChatAdapter()
        await adapter.initialize()
        assert len(adapter._models) == 12

    @pytest.mark.asyncio
    async def test_failed_scrape_uses_fallback(self, httpx_mock):
        httpx_mock.add_response(url="https://t3.chat/", status_code=500)

        adapter = T3ChatAdapter()
        await adapter.initialize()
        assert adapter._models == FALLBACK_MODELS


class TestGetModels:
    def test_returns_model_objects(self, adapter):
        models = adapter.get_models()
        assert len(models) == len(FALLBACK_MODELS)
        assert models[0].id == FALLBACK_MODELS[0]["id"]
        assert models[0].object == "model"


class TestValidateCredentials:
    def test_empty_credentials_raises(self, adapter):
        with pytest.raises(HTTPException) as exc_info:
            adapter._validate_credentials({})
        assert exc_info.value.status_code == 401

    def test_valid_credentials(self, adapter):
        cookies, sid = adapter._validate_credentials(
            {"cookies": "abc=123", "convex_session_id": "uuid-here"}
        )
        assert cookies == "abc=123"
        assert sid == "uuid-here"


class TestBuildRequestBody:
    def test_produces_correct_structure(self, adapter):
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ],
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        assert body["model"] == "gemini-3-flash"
        assert body["convexSessionId"] == "session-123"
        assert body["threadMetadata"]["id"] == "thread-456"
        assert body["isEphemeral"] is True
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["parts"] == [{"type": "text", "text": "You are helpful."}]
        assert body["messages"][1]["role"] == "user"


class TestGetOpencodeModelConfig:
    def test_returns_correct_format(self, adapter):
        configs = adapter.get_opencode_model_config()
        assert isinstance(configs, dict)
        assert len(configs) == len(FALLBACK_MODELS)
        # Check first model entry
        first_id = next(iter(configs))
        first = configs[first_id]
        assert "name" in first
        assert "limit" in first
        assert "context" in first["limit"]
        assert "output" in first["limit"]


class TestStreamParsing:
    @pytest.mark.asyncio
    async def test_text_delta_chunks(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "text-delta", "delta": "Hello"}\n\n'
            'data: {"type": "text-delta", "delta": " world"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        # Mock session refresh
        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        # Mock chat API
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        # text-delta, text-delta, finish = 3 chunks
        assert len(chunks) == 3
        assert chunks[0].choices[0].delta.content == "Hello"
        assert chunks[1].choices[0].delta.content == " world"
        assert chunks[2].choices[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_reasoning_delta_chunks(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "reasoning-delta", "delta": "thinking..."}\n\n'
            'data: {"type": "text-delta", "delta": "answer"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="deepseek-r1",
            messages=[ChatMessage(role="user", content="think")],
            stream=True,
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        assert chunks[0].choices[0].delta.reasoning_content == "thinking..."
        assert chunks[1].choices[0].delta.content == "answer"

    @pytest.mark.asyncio
    async def test_chat_completion_non_streaming(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "text-delta", "delta": "Hello"}\n\n'
            'data: {"type": "text-delta", "delta": " there"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[ChatMessage(role="user", content="hi")],
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        response = await adapter.chat_completion(request, creds)
        assert response.choices[0].message.content == "Hello there"
        assert response.choices[0].finish_reason == "stop"
        assert response.object == "chat.completion"
