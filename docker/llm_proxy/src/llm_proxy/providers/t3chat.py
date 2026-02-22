import json
import logging
import re
import time
from typing import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import HTTPException

from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelObject,
)
from llm_proxy.provider_base import ProviderAdapter

logger = logging.getLogger(__name__)

T3_CHAT_API_URL = "https://t3.chat/api/chat"
T3_SESSION_REFRESH_URL = (
    "https://t3.chat/api/trpc/auth.getActiveSessions"
    "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36"
    ),
    "Origin": "https://t3.chat",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

FALLBACK_MODELS = [
    {"id": "gemini-3-flash", "name": "Gemini 3 Flash", "owned_by": "google", "can_reason": False},
    {
        "id": "gemini-3-flash-thinking",
        "name": "Gemini 3 Flash Thinking",
        "owned_by": "google",
        "can_reason": True,
    },
    {
        "id": "gemini-3.1-pro",
        "name": "Gemini 3.1 Pro",
        "owned_by": "google",
        "can_reason": True,
    },
    {
        "id": "claude-4.6-opus",
        "name": "Claude 4.6 Opus",
        "owned_by": "anthropic",
        "can_reason": True,
    },
    {
        "id": "claude-4.6-sonnet",
        "name": "Claude 4.6 Sonnet",
        "owned_by": "anthropic",
        "can_reason": True,
    },
    {
        "id": "gpt-5.2-reasoning",
        "name": "GPT 5.2 Reasoning",
        "owned_by": "openai",
        "can_reason": True,
    },
    {
        "id": "gpt-5.2-instant",
        "name": "GPT 5.2 Instant",
        "owned_by": "openai",
        "can_reason": False,
    },
    {
        "id": "grok-4.1-fast",
        "name": "Grok 4.1 Fast",
        "owned_by": "xai",
        "can_reason": False,
    },
    {
        "id": "grok-4.1-fast-reasoning",
        "name": "Grok 4.1 Fast Reasoning",
        "owned_by": "xai",
        "can_reason": True,
    },
    {"id": "kimi-k2.5", "name": "Kimi K2.5", "owned_by": "moonshot", "can_reason": False},
    {
        "id": "kimi-k2.5-thinking",
        "name": "Kimi K2.5 Thinking",
        "owned_by": "moonshot",
        "can_reason": True,
    },
    {"id": "deepseek-r1", "name": "DeepSeek R1", "owned_by": "deepseek", "can_reason": True},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "owned_by": "deepseek", "can_reason": False},
]


class T3ChatAdapter(ProviderAdapter):
    def __init__(self):
        self._models: list[dict] = []

    @property
    def provider_id(self) -> str:
        return "t3chat"

    @property
    def display_name(self) -> str:
        return "T3 Chat"

    async def initialize(self) -> None:
        try:
            async with httpx.AsyncClient(
                headers=BROWSER_HEADERS, timeout=30.0
            ) as client:
                resp = await client.get("https://t3.chat/")
                resp.raise_for_status()
                html = resp.text

                chunk_urls = re.findall(
                    r'<script[^>]+src="(/_next/static/chunks/[a-f0-9]+\.js[^"]*)"', html
                )
                chunk_urls = [f"https://t3.chat{path}" for path in chunk_urls]

                discovered = []
                for url in chunk_urls:
                    try:
                        js_resp = await client.get(url)
                        js_resp.raise_for_status()
                        js_content = js_resp.text

                        # Look for arrays of model ID strings
                        array_matches = re.findall(
                            r'let\s+\w+\s*=\s*\[((?:"[^"]+",?\s*)+)\]', js_content
                        )
                        for array_str in array_matches:
                            model_ids = re.findall(r'"([^"]+)"', array_str)
                            models_from_chunk = []
                            for model_id in model_ids:
                                # Try to find model definition block
                                pattern = (
                                    rf'"{re.escape(model_id)}":\s*\{{.*?'
                                    rf'id:\s*"([^"]+)"'
                                    rf'(?:.*?name:\s*"([^"]+)")?'
                                    rf'(?:.*?provider:\s*"([^"]+)")?'
                                    rf'(?:.*?developer:\s*"([^"]+)")?'
                                )
                                defn = re.search(pattern, js_content, re.DOTALL)
                                name = model_id
                                owned_by = "t3chat"
                                if defn:
                                    name = defn.group(2) or model_id
                                    owned_by = defn.group(3) or defn.group(4) or "t3chat"

                                can_reason = "thinking" in model_id or "reasoning" in model_id
                                models_from_chunk.append(
                                    {
                                        "id": model_id,
                                        "name": name,
                                        "owned_by": owned_by,
                                        "can_reason": can_reason,
                                    }
                                )

                            if len(models_from_chunk) > 10:
                                discovered = models_from_chunk
                                break

                    except Exception:
                        continue

                    if discovered:
                        break

                if discovered:
                    self._models = discovered
                else:
                    logger.warning("T3 model discovery found no models, using fallback list")
                    self._models = FALLBACK_MODELS

        except Exception as e:
            logger.warning(f"T3 model discovery failed, using fallback list: {e}")
            self._models = FALLBACK_MODELS

        logger.info(f"T3 Chat: discovered {len(self._models)} models")

    def get_models(self) -> list[ModelObject]:
        return [
            ModelObject(id=m["id"], created=0, owned_by=m.get("owned_by", "t3chat"))
            for m in self._models
        ]

    def get_opencode_model_config(self) -> list[dict]:
        return [
            {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "can_reason": m.get("can_reason", False),
                "supports_attachments": False,
                "context_window": 200000,
                "default_max_tokens": 16000,
                "cost_per_1m_in": 0,
                "cost_per_1m_out": 0,
                "cost_per_1m_in_cached": 0,
                "cost_per_1m_out_cached": 0,
            }
            for m in self._models
        ]

    def _validate_credentials(self, credentials: dict) -> tuple[str, str]:
        cookies = credentials.get("cookies")
        convex_session_id = credentials.get("convex_session_id")
        if not cookies or not convex_session_id:
            raise HTTPException(
                status_code=401,
                detail="T3 credentials must include 'cookies' and 'convex_session_id'",
            )
        return (cookies, convex_session_id)

    async def _refresh_session(self, client: httpx.AsyncClient, cookies: str) -> str:
        try:
            resp = await client.get(
                T3_SESSION_REFRESH_URL,
                headers={
                    "Cookie": cookies,
                    "Content-Type": "application/json",
                    "trpc-accept": "application/jsonl",
                },
            )
            new_session = resp.headers.get("x-workos-session")
            if new_session:
                parts = cookies.split("; ")
                parts = [p for p in parts if not p.startswith("wos-session=")]
                parts.append(f"wos-session={new_session}")
                return "; ".join(parts)
        except Exception as e:
            logger.warning(f"Session refresh failed: {e}")
        return cookies

    def _build_t3_request_body(
        self, request: ChatCompletionRequest, convex_session_id: str, thread_id: str
    ) -> dict:
        converted_messages = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                parts = [{"type": "text", "text": msg.content}]
            elif isinstance(msg.content, list):
                parts = msg.content
            else:
                parts = []

            converted_messages.append(
                {
                    "id": str(uuid4()),
                    "role": msg.role,
                    "parts": parts,
                    "attachments": [],
                }
            )

        # Check for reasoning_effort in extra fields
        reasoning_effort = "medium"
        if hasattr(request, "reasoning_effort") and request.reasoning_effort:
            reasoning_effort = request.reasoning_effort

        return {
            "messages": converted_messages,
            "threadMetadata": {"id": thread_id},
            "responseMessageId": str(uuid4()),
            "model": request.model,
            "convexSessionId": convex_session_id,
            "modelParams": {
                "reasoningEffort": reasoning_effort,
                "includeSearch": False,
            },
            "preferences": {
                "name": "",
                "occupation": "",
                "selectedTraits": [],
                "additionalInfo": "",
            },
            "userInfo": {
                "timezone": "America/New_York",
                "locale": "en-US",
            },
            "isEphemeral": True,
        }

    async def _iter_t3_sse(
        self, client: httpx.AsyncClient, cookies: str, body: dict, thread_id: str
    ) -> AsyncIterator[tuple[str, dict | None]]:
        resp = await client.send(
            client.build_request(
                "POST",
                T3_CHAT_API_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookies,
                    "Referer": f"https://t3.chat/chat/{thread_id}",
                    "Accept": "*/*",
                },
            ),
            stream=True,
        )

        if resp.status_code < 200 or resp.status_code >= 300:
            error_body = await resp.aread()
            raise HTTPException(
                status_code=502,
                detail=f"T3.chat returned {resp.status_code}: {error_body.decode()}",
            )

        async for line in resp.aiter_lines():
            if not line:
                continue
            if not line.startswith("data: "):
                continue

            data_str = line[6:]
            if data_str == "[DONE]":
                yield ("done", None)
                return

            try:
                parsed = json.loads(data_str)
                event_type = parsed.get("type", "")
                yield (event_type, parsed)
            except json.JSONDecodeError:
                continue

    async def chat_completion_stream(
        self, request: ChatCompletionRequest, credentials: dict
    ) -> AsyncIterator[ChatCompletionChunk]:
        cookies, convex_session_id = self._validate_credentials(credentials)
        thread_id = str(uuid4())

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10),
            headers=BROWSER_HEADERS,
        ) as client:
            cookies = await self._refresh_session(client, cookies)
            body = self._build_t3_request_body(request, convex_session_id, thread_id)
            completion_id = f"chatcmpl-{uuid4().hex[:24]}"
            created = int(time.time())

            async for event_type, event in self._iter_t3_sse(client, cookies, body, thread_id):
                if event_type == "text-delta":
                    text = self._extract_delta_text(event)
                    if text is None:
                        continue
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(content=text),
                                finish_reason=None,
                            )
                        ],
                    )

                elif event_type == "reasoning-delta":
                    text = self._extract_delta_text(event)
                    if text is None:
                        continue
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(reasoning_content=text),
                                finish_reason=None,
                            )
                        ],
                    )

                elif event_type == "finish":
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(),
                                finish_reason="stop",
                            )
                        ],
                    )

                elif event_type == "done":
                    return

    def _extract_delta_text(self, event: dict) -> str | None:
        delta = event.get("delta")
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict):
            return delta.get("text")
        return None

    async def chat_completion(
        self, request: ChatCompletionRequest, credentials: dict
    ) -> ChatCompletionResponse:
        accumulated_text = ""
        completion_id = f"chatcmpl-{uuid4().hex[:24]}"

        async for chunk in self.chat_completion_stream(request, credentials):
            for choice in chunk.choices:
                if choice.delta.content:
                    accumulated_text += choice.delta.content

        return ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=accumulated_text),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )
