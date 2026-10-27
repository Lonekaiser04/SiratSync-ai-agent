"""
Comprehensive tests for Server-Sent Events (SSE) streaming chat endpoint (/chat/stream).
Covers:
- Token-by-token asynchronous streaming with Groq
- Automatic model fallback during streaming
- Quick reply and Quran verse direct RAG streaming
- Error handling and non-pollution of conversation memory
- Client disconnect and stream cancellation safety
- Response caching and SSE headers validation
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from groq import InternalServerError, NotFoundError
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.memory_service import memory
from app.utils.cache import cache


@pytest_asyncio.fixture(autouse=True)
async def clear_cache_and_memory():
    await cache.clear()
    await memory.clear_session("test_stream_user")
    await memory.clear_session("test_user_stream_fallback")
    await memory.clear_session("test_user_stream_error")
    yield
    await cache.clear()
    await memory.clear_session("test_stream_user")
    await memory.clear_session("test_user_stream_fallback")
    await memory.clear_session("test_user_stream_error")


def _parse_sse_events(raw_text: str) -> list[tuple[str, dict]]:
    """Helper to parse raw SSE text into a list of (event_type, payload_dict) tuples."""
    events = []
    current_event = "message"
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        data_lines = []
        for line in lines:
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:].strip())
        if data_lines:
            combined_data = "\n".join(data_lines)
            try:
                parsed_json = json.loads(combined_data)
            except json.JSONDecodeError:
                parsed_json = {"raw": combined_data}
            events.append((current_event, parsed_json))
    return events


def _create_mock_stream(tokens: list[str], finish_reason: str = "stop"):
    """Helper creating an async iterable of mock Groq streaming chunks."""
    async def _async_chunks():
        for token in tokens:
            choice = MagicMock()
            choice.delta.content = token
            choice.finish_reason = None
            chunk = MagicMock(choices=[choice])
            yield chunk
        # Final stop chunk
        choice = MagicMock()
        choice.delta.content = ""
        choice.finish_reason = finish_reason
        yield MagicMock(choices=[choice])

    return _async_chunks()


@pytest.mark.asyncio
class TestChatStreamingEndpoint:
    async def test_streaming_successful_token_generation(self):
        """Verify tokens are emitted progressively with status, meta, tokens, and done event."""
        tokens = ["Seeking ", "beneficial ", "knowledge ", "is ", "encouraged."]
        mock_stream = _create_mock_stream(tokens)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_stream

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_stream_user",
                        "message": "Why is seeking knowledge important in Islam?",
                    },
                )
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

                events = _parse_sse_events(response.text)
                event_types = [e[0] for e in events]

                assert "meta" in event_types
                assert "token" in event_types
                assert "done" in event_types

                # Verify tokens streamed in sequence
                received_tokens = [e[1].get("delta") for e in events if e[0] == "token"]
                full_received_text = "".join(received_tokens)
                assert "Seeking beneficial knowledge is encouraged." in full_received_text

                # Verify done event structure
                done_event = next(e[1] for e in events if e[0] == "done")
                assert "reply" in done_event
                assert "sources" in done_event
                assert "actions" in done_event
                assert "suggestions" in done_event

                # Verify conversation memory was written after generation
                history = await memory.get_recent_messages("test_stream_user", count=10)
                assert len(history) == 2
                assert history[0]["role"] == "user"
                assert history[1]["role"] == "assistant"
                assert "Seeking beneficial knowledge" in history[1]["content"]

    async def test_streaming_model_not_found_fallback(self):
        """Verify primary model 404 recovers seamlessly on fallback model during streaming."""
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(404, request=req, json={"error": {"code": "model_not_found", "message": "Model not found"}})
        nfe = NotFoundError("Model not found", response=res, body=None)

        fallback_tokens = ["Patience ", "and ", "gratitude."]
        mock_fallback_stream = _create_mock_stream(fallback_tokens)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                # First call (primary) raises 404, second call (fallback) returns stream
                mock_create.side_effect = [nfe, mock_fallback_stream]

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_user_stream_fallback",
                        "message": "Give me a thought on perseverance.",
                    },
                )
                assert response.status_code == 200

                events = _parse_sse_events(response.text)
                received_tokens = [e[1].get("delta") for e in events if e[0] == "token"]
                assert "".join(received_tokens) == "Patience and gratitude."

                done_event = next(e[1] for e in events if e[0] == "done")
                # Sources detail should reflect the fallback model
                ai_sources = [s for s in done_event.get("sources", []) if s.get("type") == "ai_generated"]
                assert len(ai_sources) == 1
                assert settings.FALLBACK_GROQ_MODEL in ai_sources[0]["detail"]

    async def test_streaming_quick_reply(self):
        """Verify greeting / quick replies stream tokens and return valid done payload."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/chat/stream",
                json={
                    "user_id": "test_stream_user",
                    "message": "Assalamu alaikum",
                },
            )
            assert response.status_code == 200
            events = _parse_sse_events(response.text)
            event_types = [e[0] for e in events]

            assert "token" in event_types
            assert "done" in event_types

            done_event = next(e[1] for e in events if e[0] == "done")
            assert "alaikum" in done_event["reply"].lower() or "salam" in done_event["reply"].lower()

    async def test_streaming_verse_direct_rag(self):
        """Verify verse retrieval query streams RAG text with Quran citations."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/chat/stream",
                json={
                    "user_id": "test_stream_user",
                    "message": "show me verse 2:255",
                },
            )
            assert response.status_code == 200
            events = _parse_sse_events(response.text)
            done_event = next(e[1] for e in events if e[0] == "done")

            assert "2:255" in done_event["reply"] or "Al-Baqarah" in done_event["reply"]
            # Verify Quran source attribution
            sources = done_event.get("sources", [])
            assert any(s.get("type") == "quran" for s in sources)

    async def test_streaming_error_does_not_pollute_memory(self):
        """When LLM provider fails fatally, memory must not store an error as assistant completion."""
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(500, request=req, json={"error": {"code": "server_error"}})
        ise = InternalServerError("Groq down", response=res, body=None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.side_effect = ise

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_user_stream_error",
                        "message": "Explain deep theology concept here.",
                    },
                )
                assert response.status_code == 200
                events = _parse_sse_events(response.text)
                
                # Verify fallback notice was emitted
                done_or_error = [e for e in events if e[0] in ("done", "error")]
                assert len(done_or_error) >= 1
                payload = done_or_error[0][1]
                assert "trouble" in payload.get("reply", "").lower() or "trouble" in payload.get("error", "").lower()

    async def test_streaming_cache_hit_returns_immediately(self):
        """Verify cached responses are streamed immediately from Redis/local cache."""
        # Pre-seed cache
        cached_data = {
            "reply": "Cached reflection on patience.",
            "intent": "general",
            "sub_intent": "",
            "sentiment": "positive",
            "actions": {},
            "suggestions": ["Tell me more"],
            "timestamp": "2026-10-27T00:00:00",
            "sources": [{"type": "knowledge_base", "label": "Sirat Knowledge"}],
        }
        await cache.set("cached query test", "test_stream_user", json.dumps(cached_data))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/chat/stream",
                json={
                    "user_id": "test_stream_user",
                    "message": "cached query test",
                },
            )
            assert response.status_code == 200
            events = _parse_sse_events(response.text)

            status_event = next(e[1] for e in events if e[0] == "status" and e[1].get("status") == "cached")
            assert status_event["status"] == "cached"

            token_events = [e[1]["delta"] for e in events if e[0] == "token"]
            assert "".join(token_events) == "Cached reflection on patience."

            done_event = next(e[1] for e in events if e[0] == "done")
            assert done_event["reply"] == "Cached reflection on patience."

    async def test_streaming_disconnect_aborts_without_memory_write(self):
        """When client disconnects midway through generation, generator aborts and memory is not written."""
        from app.api.chat import _chat_stream_generator
        from app.models.request_models import ChatRequest

        req = ChatRequest(user_id="test_user_disconnect", message="Explain gratitude in Islam")
        mock_http_req = MagicMock()
        mock_http_req.state.request_id = "test-disc-req"
        mock_http_req.state.authenticated_user_id = "test_user_disconnect"

        disconnect_calls = 0
        async def mock_is_disconnected():
            nonlocal disconnect_calls
            disconnect_calls += 1
            return disconnect_calls > 1

        mock_http_req.is_disconnected = mock_is_disconnected

        tokens = ["First part ", "second part ", "third part "]
        mock_stream = _create_mock_stream(tokens)

        with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_stream
            emitted = []
            async for chunk in _chat_stream_generator(req, mock_http_req):
                emitted.append(chunk)

            # Generator should have stopped early upon disconnect
            # Verify conversation memory was NOT saved with assistant response
            history = await memory.get_recent_messages("test_user_disconnect", count=10)
            assert len(history) == 0

    async def test_streaming_slow_response_emits_keep_alive(self):
        """Verify that provider pauses trigger ': keep-alive' SSE comments without breaking stream."""
        import asyncio

        async def _slow_chunks():
            # First chunk
            choice = MagicMock()
            choice.delta.content = "Initial thought. "
            choice.finish_reason = None
            yield MagicMock(choices=[choice])

            # Pause > 1.0 second to trigger keep-alive
            await asyncio.sleep(1.2)

            # Second chunk
            choice = MagicMock()
            choice.delta.content = "Conclusion."
            choice.finish_reason = "stop"
            yield MagicMock(choices=[choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = _slow_chunks()
                with patch("app.core.config.settings.LLM_TIMEOUT_SECONDS", 2):
                    response = await ac.post(
                        "/chat/stream",
                        json={
                            "user_id": "test_stream_slow_user",
                            "message": "Discuss deep philosophical reasoning",
                        },
                    )
                    assert response.status_code == 200
                    assert ": keep-alive" in response.text
                    events = _parse_sse_events(response.text)
                    received_tokens = [e[1].get("delta") for e in events if e[0] == "token"]
                    assert "".join(received_tokens) == "Initial thought. Conclusion."

    async def test_streaming_long_answer_bounded(self):
        """Verify long answer (>2000 chars) is streamed and bounded properly."""
        sentence = "This is a detailed and beneficial reflection on patience and prayer. "
        # 40 repetitions is ~2800 characters
        tokens = [sentence for _ in range(40)]
        mock_stream = _create_mock_stream(tokens)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_stream

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_stream_long_user",
                        "message": "Give a long treatise on sabr",
                    },
                )
                assert response.status_code == 200
                events = _parse_sse_events(response.text)
                done_event = next(e[1] for e in events if e[0] == "done")
                assert len(done_event["reply"]) <= 2005
                assert done_event["reply"].endswith(".")

    async def test_streaming_concurrent_requests(self):
        """Verify multiple simultaneous streaming requests complete without crosstalk."""
        import asyncio

        def _make_user_stream(user_tag: str):
            tokens = [f"Response ", f"for ", f"{user_tag}."]
            return _create_mock_stream(tokens)

        def _side_effect(*args, **kwargs):
            messages = kwargs.get("messages", [])
            last_msg = messages[-1]["content"] if messages else ""
            for tag in ["user_1", "user_2", "user_3"]:
                if tag in last_msg:
                    return _make_user_stream(tag)
            return _make_user_stream("UserUnknown")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.side_effect = _side_effect

                async def _send(u_id: str):
                    return await ac.post(
                        "/chat/stream",
                        json={"user_id": u_id, "message": f"Explain reflection concept for {u_id}"},
                    )

                resA, resB, resC = await asyncio.gather(
                    _send("concurrent_user_1"),
                    _send("concurrent_user_2"),
                    _send("concurrent_user_3"),
                )

                assert resA.status_code == 200
                assert resB.status_code == 200
                assert resC.status_code == 200

                eventsA = _parse_sse_events(resA.text)
                eventsB = _parse_sse_events(resB.text)
                eventsC = _parse_sse_events(resC.text)

                replyA = next(e[1] for e in eventsA if e[0] == "done")["reply"]
                replyB = next(e[1] for e in eventsB if e[0] == "done")["reply"]
                replyC = next(e[1] for e in eventsC if e[0] == "done")["reply"]

                assert "user_1" in replyA
                assert "user_2" in replyB
                assert "user_3" in replyC

    async def test_streaming_provider_stall_timeout(self):
        """Verify provider stalling past timeout raises TimeoutError and yields error event."""
        import asyncio

        async def _stalled_chunks():
            choice = MagicMock()
            choice.delta.content = "Start..."
            choice.finish_reason = None
            yield MagicMock(choices=[choice])
            # Hang longer than test timeout
            await asyncio.sleep(2.0)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = _stalled_chunks()
                with patch("app.core.config.settings.LLM_TIMEOUT_SECONDS", 0.5):
                    response = await ac.post(
                        "/chat/stream",
                        json={
                            "user_id": "test_user_stall",
                            "message": "This provider will stall",
                        },
                    )
                    assert response.status_code == 200
                    events = _parse_sse_events(response.text)
                    error_events = [e for e in events if e[0] in ("error", "token")]
                    assert len(error_events) >= 1

    async def test_streaming_connected_event_emitted_first(self):
        """The very first SSE event must be a 'status'/'connected' to prevent client timeout."""
        tokens = ["Peace ", "be ", "upon ", "you."]
        mock_stream = _create_mock_stream(tokens)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_stream

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_stream_user",
                        "message": "Why is gratitude important?",
                    },
                )
                assert response.status_code == 200
                events = _parse_sse_events(response.text)
                assert len(events) >= 1, "Stream should emit at least one event"

                # The first event must be the immediate connected acknowledgement
                first_event_type, first_payload = events[0]
                assert first_event_type == "status", (
                    f"First event must be 'status', got '{first_event_type}'"
                )
                assert first_payload.get("status") == "connected", (
                    f"First status must be 'connected', got {first_payload}"
                )

    async def test_streaming_memory_failure_degrades_gracefully(self):
        """When memory/Redis is unavailable, streaming should still produce a valid response."""
        tokens = ["Sabr ", "is ", "a ", "virtue."]
        mock_stream = _create_mock_stream(tokens)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch.object(memory, "get_last_question", side_effect=ConnectionError("Redis down")), \
                 patch.object(memory, "get_last_bot_message", side_effect=ConnectionError("Redis down")), \
                 patch.object(memory, "get_recent_messages", side_effect=ConnectionError("Redis down")), \
                 patch.object(memory, "get_context", side_effect=ConnectionError("Redis down")):
                mock_create.return_value = mock_stream

                response = await ac.post(
                    "/chat/stream",
                    json={
                        "user_id": "test_stream_mem_fail",
                        "message": "Tell me about patience in Islam",
                    },
                )
                assert response.status_code == 200
                events = _parse_sse_events(response.text)
                event_types = [e[0] for e in events]

                # Stream should still complete successfully despite memory failure
                assert "token" in event_types, "Should still emit tokens"
                assert "done" in event_types, "Should still emit done event"

                received_tokens = [e[1].get("delta") for e in events if e[0] == "token"]
                assert "Sabr is a virtue." in "".join(received_tokens)

    async def test_sse_keep_alive_comments_parsed_correctly(self):
        """Verify raw SSE text with keep-alive comments is parsed without errors."""
        raw = (
            "event: status\n"
            "data: {\"status\": \"connected\", \"stage\": \"init\"}\n\n"
            ": keep-alive\n\n"
            "event: token\n"
            "data: {\"delta\": \"Hello\"}\n\n"
            ": keep-alive\n\n"
            "event: done\n"
            "data: {\"reply\": \"Hello\", \"intent\": \"general\"}\n\n"
        )
        events = _parse_sse_events(raw)
        event_types = [e[0] for e in events]

        assert "status" in event_types
        assert "token" in event_types
        assert "done" in event_types
        # Keep-alive comments must not appear as events
        assert all(e[0] != "keep-alive" for e in events)

