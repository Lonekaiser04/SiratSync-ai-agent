import os
import re
import logging
from groq import Groq

logger = logging.getLogger(__name__)

llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def _extract_english_only(rag_data: str) -> str:
    """
    Extract ONLY English text from RAG data.
    Skip all Arabic, Urdu, Kashmiri, transliteration.
    """
    english_lines = []
    
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        
        # Keep only English content
        if stripped.startswith("VERSE REFERENCE:"):
            english_lines.append(stripped)
        elif stripped.startswith("ENGLISH:"):
            text = stripped.replace("ENGLISH:", "").strip()
            # Remove italic markers
            if text.startswith("_") and text.endswith("_"):
                text = text[1:-1]
            english_lines.append(text)
        elif stripped.startswith("SUMMARY:"):
            english_lines.append(stripped)
        elif stripped.startswith("MAIN TOPICS:"):
            english_lines.append(stripped)
        elif stripped.startswith("SURAH:"):
            english_lines.append(stripped)
        elif stripped.startswith("SURAH NUMBER:"):
            english_lines.append(stripped)
        elif stripped.startswith("VERSES:"):
            english_lines.append(stripped)
        elif stripped.startswith("REVELATION TYPE:"):
            english_lines.append(stripped)
        elif stripped.startswith("JUZ:"):
            english_lines.append(stripped)
        elif stripped.startswith("SIMILAR VERSES:"):
            english_lines.append(stripped)
        elif stripped.startswith("  -"):
            english_lines.append(stripped)
    
    return "\n".join(english_lines)


def _format_rag_data_direct(rag_data: str) -> str:
    """
    Safe fallback formatter when LLM call fails.
    Handles the structured format produced by get_rag_data_for_llm:
      VERSE REFERENCE: ...
      ARABIC: ...
      ENGLISH: ...
      URDU: ...
      KASHMIRI TAFSIR: ...
      SURAH: ...
      SUMMARY: ...
    """
    lines_out = ["📖 **Quranic Guidance:**\n"]
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines_out.append("")
            continue
        if stripped.startswith("VERSE REFERENCE:"):
            ref = stripped.replace("VERSE REFERENCE:", "").strip()
            lines_out.append(f"\n**📍 {ref}**")
        elif stripped.startswith("SURAH:"):
            lines_out.append(f"\n**{stripped.replace('SURAH:', '📖').strip()}**")
        elif stripped.startswith("ARABIC:"):
            lines_out.append(f" {stripped.replace('ARABIC:', '').strip()}")
        elif stripped.startswith("ENGLISH:"):
            lines_out.append(f"{stripped.replace('ENGLISH:', '').strip()}_")
        elif stripped.startswith("URDU:"):
            lines_out.append(f"{stripped.replace('URDU:', '').strip()}")
        elif stripped.startswith("KASHMIRI TAFSIR:") or stripped.startswith("KASHMIRI:"):
            ks = re.sub(r"^KASHMIRI( TAFSIR)?:", "", stripped).strip()
            lines_out.append(f"🏔️ **Kashmiri:** {ks}")
        elif stripped.startswith("TRANSLITERATION:"):
            lines_out.append(f"🔊 _{stripped.replace('TRANSLITERATION:', '').strip()}_")
        elif stripped.startswith("SUMMARY:"):
            lines_out.append(f"📝 {stripped.replace('SUMMARY:', '').strip()}")
        elif stripped.startswith("MAIN TOPICS:"):
            lines_out.append(f"📌 **Topics:** {stripped.replace('MAIN TOPICS:', '').strip()}")
        elif stripped.startswith("VERSES:"):
            lines_out.append(f"📊 {stripped}")
        elif stripped.startswith("SIMILAR VERSES:"):
            lines_out.append(f"\n📎 **Similar Verses:**")
        elif stripped.startswith("  -"):
            lines_out.append(stripped)
        elif stripped.startswith("RELATED SURAHS:"):
            lines_out.append(f"\n📖 **Related Surahs:**")
        elif stripped.startswith("  -") or stripped.startswith("VERSE:"):
            lines_out.append(stripped.replace("VERSE:", "\n**Verse:**"))
        else:
            lines_out.append(stripped)

    lines_out.append("\n🤲 _Open the full surah in the app for complete tafsir._")
    return "\n".join(lines_out)


def _call_llm_with_rag(user_query: str, rag_data: str, user_profile: dict) -> str:
    """
    English in, English out. Nothing else.
    LLM never sees or generates non-English text.
    """
    
    # Extract only English content from RAG data
    english_only = _extract_english_only(rag_data)
    
    if not english_only.strip():
        return "I couldn't find relevant information in English."
    
    try:
        response = llm.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": """You are SiratSync AI, an Islamic assistant.

You will receive Quran reference data in English only.
Your job:
1. Answer the user's question using the provided data strictly
2. Reference verses properly (e.g., "Surah Al-Baqarah 2:255 says...")
3. Keep explanations clear and concise
4. Be scholarly but warm
5. NEVER attempt to write Arabic, Urdu, or Kashmiri text
6. Respond ONLY in English
7. Only use the information provided. Do not add, question, or correct it
8.End with: "📌 For accurate verse details, ask by reference (e.g., 94:5)."
.
""",
                },
                {
                    "role": "user", 
                    "content": f"Based on this information:\n\n{english_only}\n\nUser asks: {user_query}\n\nProvide a helpful English response:"
                },
            ],
            temperature=0.3,
            max_tokens=600,
        )
        
        english_response = response.choices[0].message.content.strip()
        logger.info(f"✅ English-only response generated ({len(english_response)} chars)")
        return english_response
        
    except Exception as e:
        logger.error(f"⚠️ LLM failed: {e}")
        return _format_rag_data_direct(rag_data)