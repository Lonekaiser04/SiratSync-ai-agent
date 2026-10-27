import pytest
from app.services.memory_service import MemoryManager, _CHAT_TTL_SECONDS, _MAX_MESSAGES_STORED, _ANONYMOUS_IDS
from app.prompts.system_prompt import SYSTEM_PROMPT
from app.utils.helpers import _format_rag_data_direct


def test_memory_service_ttl_and_bounds():
    """Verify 7-day TTL and 30-message bounded storage."""
    # 7 days in seconds = 7 * 86400 = 604800
    assert _CHAT_TTL_SECONDS == 7 * 86400, "TTL must be 7 days"
    assert _MAX_MESSAGES_STORED == 30, "Max messages must be bounded to 30"


def test_memory_service_anonymous_isolation():
    """Verify unauthenticated/anonymous IDs are recognized and isolated."""
    for anon_id in ["anonymous", "guest", "none", "unknown", "null", "undefined"]:
        assert anon_id in _ANONYMOUS_IDS


import uuid

@pytest.mark.asyncio
async def test_memory_service_deduplication():
    """Verify consecutive identical messages are not stored twice."""
    mem = MemoryManager()
    user_id = f"test_user_dedup_{uuid.uuid4().hex}"

    await mem.add_message(user_id, "user", "Assalamu Alaikum")
    await mem.add_message(user_id, "user", "Assalamu Alaikum")  # Duplicate
    await mem.add_message(user_id, "assistant", "Wa Alaikum Assalam")
    await mem.add_message(user_id, "assistant", "Wa Alaikum Assalam")  # Duplicate
    await mem.add_message(user_id, "user", "How are you?")

    history = await mem.get_recent_messages(user_id, count=10)
    # Consecutive duplicates should have been filtered out
    user_messages = [m["content"] for m in history if m["role"] == "user"]
    assistant_messages = [m["content"] for m in history if m["role"] == "assistant"]

    assert user_messages.count("Assalamu Alaikum") == 1
    assert assistant_messages.count("Wa Alaikum Assalam") == 1
    assert "How are you?" in user_messages


@pytest.mark.asyncio
async def test_consistency_calculation_does_not_invent_struggles():
    """Users with 0 recorded struggles must not be labeled as 'struggling'."""
    mem = MemoryManager()
    user_id = f"neutral_user_{uuid.uuid4().hex}"

    # Add 6 normal questions without any struggle mentions
    for i in range(6):
        await mem.add_message(user_id, "user", f"Tell me about Islamic history topic {i}")
        await mem.add_message(user_id, "assistant", f"Here is information on topic {i}")

    profile = await mem.get_user_profile(user_id)
    # Must NOT default to "struggling" when struggle_count is 0
    assert profile["consistency"] != "struggling", f"Profile should not default to struggling: {profile}"


def test_system_prompt_rules_against_assumptions_and_promotions():
    """Verify system prompt explicitly prevents invented struggles and open-app messages."""
    prompt_lower = SYSTEM_PROMPT.lower()

    # Rule against repetitive personal assumptions
    assert "struggling with consistency" in prompt_lower or "personal assumptions" in prompt_lower or "invent struggles" in prompt_lower
    # Rule against 'open app' promotional spam
    assert "open the app" in prompt_lower or "promotional" in prompt_lower or "external app" in prompt_lower
    # Useful follow-up question guidance
    assert "follow-up question" in prompt_lower


def test_helpers_format_tafsir_has_no_open_app_prompts():
    """Verify _format_rag_data_direct does not append unsolicited 'open the app' messages."""
    sample_rag = (
        "VERSE REFERENCE: 1:1\n"
        "SURAH: Al-Fatihah\n"
        "ARABIC: بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ\n"
        "ENGLISH: In the name of Allah, the Entirely Merciful, the Especially Merciful.\n"
        "KASHMIRI TAFSIR: تفسیری وضاحت\n"
    )

    formatted = _format_rag_data_direct(sample_rag)
    assert "Open the full surah in the app" not in formatted
    assert "open the app" not in formatted.lower()
