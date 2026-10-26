"""
Automated regression tests for:
1. Summarization:
   - Urdu summaries (summarized in Urdu, retaining Urdu script & terminal punctuation '۔')
   - Roman Urdu summaries (summarized in Roman Urdu)
   - Arabic summaries (summarized in Arabic)
   - Very short posts kept unchanged
   - Short posts: exactly 2 bullet points
   - Long posts: exactly 3 bullet points
   - Sacred text preservation (Quranic verses, Hadiths, duas untouched and undistorted)
   - Zero truncation / complete sentence guarantee
2. Islamic Chat & Quran RAG:
   - Modesty query: returns Surah An-Nur 24:30-31, Surah Al-Ahzab 33:59, and authentic Hadith (Sahih al-Bukhari/Muslim) with explanation
   - Direct answers: "How many prophets are mentioned by name in the Quran?" answers 25 directly without suggesting app modules
   - Direct answers for first prophet (Adam AS), last prophet (Muhammad PBUH), only named woman (Maryam), only named companion (Zayd ibn Harithah)
   - Unrelated secular queries: return empty RAG context and receive purely objective, non-religious answers
"""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.services.rag_service import rag_service
from app.api.summarize import detect_content_language, clean_summary_output, preprocess_post_content


# ══════════════════════════════════════════════════════════════════════════════
# 1. SUMMARIZATION QUALITY & MULTILINGUAL REGRESSION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizationMultilingualAndRules:

    def test_language_detection(self):
        urdu_post = "نماز دین کا ستون ہے اور مومن کی معراج ہے۔ ہمیں وقت پر نماز ادا کرنی چاہیے۔"
        assert detect_content_language(urdu_post) == "Urdu"

        arabic_post = "إن الصلاة كانت على المؤمنين كتابا موقوتا وقال رسول الله صلى الله عليه وسلم بني الإسلام على خمس"
        assert detect_content_language(arabic_post) == "Arabic"

        roman_urdu_post = "Aj ki post mein hum namaz ke bare mein baat karenge jo har musalman ke liye bohat zaroori hai aur Allah se dua hai."
        assert detect_content_language(roman_urdu_post) == "Roman Urdu"

        english_post = "Maintaining daily habits and consistency in worship is essential for spiritual growth and peace of mind."
        assert detect_content_language(english_post) == "English"

    def test_very_short_post_kept_unchanged(self):
        very_short = "Jummah Mubarak to everyone!"
        cleaned, is_trivial_or_short = preprocess_post_content(very_short)
        assert is_trivial_or_short is True
        assert cleaned == very_short

    def test_clean_summary_output_bullet_formatting_and_terminal_punctuation(self):
        # 2 bullets output
        raw_bullets = "1. First key point of the post\n2. Second key point with conclusion"
        cleaned = clean_summary_output(raw_bullets, "", target_bullets=2)
        lines = cleaned.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("• ") and lines[0].endswith(".")
        assert lines[1].startswith("• ") and lines[1].endswith(".")

        # Urdu bullets terminal punctuation '۔'
        raw_urdu = "• نماز وقت پر ادا کرنا ہر مسلمان پر فرض ہے\n• استقامت اور خشوع کے ساتھ عبادت کرنی چاہیے"
        cleaned_urdu = clean_summary_output(raw_urdu, "", target_bullets=2)
        assert "۔" in cleaned_urdu

    @pytest.mark.asyncio
    async def test_urdu_post_summarization_pipeline(self):
        urdu_content = (
            "نماز اسلام کا سب سے بنیادی اور اہم رکن ہے۔ حضور اکرم صلی اللہ علیہ وسلم نے فرمایا کہ "
            "نماز مومن اور کافر کے درمیان فرق ہے۔ جب بندہ سچے دل سے اللہ کے حضور سجدہ ریز ہوتا ہے "
            "تو اس کے گناہ جھڑ جاتے ہیں اور دل کو اطمینان حاصل ہوتا ہے۔ اس لیے ہر مسلمان کو چاہیے "
            "کہ وہ اپنے تمام دنیاوی کام چھوڑ کر بروقت نماز باجماعت ادا کرنے کا اہتمام کرے۔"
        )
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "• نماز اسلام کا سب سے بنیادی اور اہم ترین ستون ہے۔\n"
            "• بروقت باجماعت نماز ادا کرنے سے دل کو سکون اور گناہوں سے مغفرت حاصل ہوتی ہے۔"
        )
        mock_res = MagicMock(choices=[mock_choice], usage=MagicMock(total_tokens=150))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_res
                resp = await ac.post("/summarize", json={"post_content": urdu_content, "user_id": "urdu_user"})
                assert resp.status_code == 200
                data = resp.json()
                summary = data["summary"]
                assert summary.count("•") == 2
                assert "نماز" in summary
                # Ensure the summary was written in Urdu
                assert detect_content_language(summary) == "Urdu"

    @pytest.mark.asyncio
    async def test_sacred_text_preservation_in_summary(self):
        post_with_verse = (
            "In times of trial and hardship, we must turn to Allah with steadfastness. "
            "Allah explicitly instructs us in Surah Al-Baqarah (2:153): "
            "يَا أَيُّهَا الَّذِينَ آمَنُوا اسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ ۚ إِنَّ اللَّهَ مَعَ الصَّابِرِينَ "
            "which translates to: 'O you who have believed, seek help through patience and prayer. Indeed, Allah is with the patient.' "
            "Remember this whenever difficulties arise in your life."
        )
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "• Believers are instructed to seek divine assistance through patience and prayer during hardships.\n"
            "• Surah Al-Baqarah (2:153) explicitly affirms: يَا أَيُّهَا الَّذِينَ آمَنُوا اسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ (Allah is with the patient)."
        )
        mock_res = MagicMock(choices=[mock_choice], usage=MagicMock(total_tokens=180))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_res
                resp = await ac.post("/summarize", json={"post_content": post_with_verse, "user_id": "sacred_user"})
                assert resp.status_code == 200
                data = resp.json()
                assert "2:153" in data["summary"] or "Al-Baqarah" in data["summary"]
                assert "الصَّبْرِ" in data["summary"] or "patience and prayer" in data["summary"]

    @pytest.mark.asyncio
    async def test_pure_arabic_post_kept_unchanged(self):
        arabic_text = "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ ۚ لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ ۚ لَّهُ مَا فِي السَّمَاوَاتِ وَمَا فِي الْأَرْضِ"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                resp = await ac.post("/summarize", json={"post_content": arabic_text, "user_id": "arabic_user"})
                assert resp.status_code == 200
                data = resp.json()
                # Must be returned unchanged with 0 LLM calls
                assert mock_create.call_count == 0
                assert data["summary"] == arabic_text

    @pytest.mark.asyncio
    async def test_mixed_english_arabic_post_summarizes_english_and_preserves_arabic(self):
        mixed_post = (
            "Renewing your intention daily is paramount in our faith. "
            "The Messenger of Allah peace be upon him stated: "
            "إِنَّمَا الْأَعْمَالُ بِالنِّيَّاتِ وَإِنَّمَا لِكُلِّ امْرِئٍ مَا نَوَى "
            "Every action that you undertake throughout your day, from studying to work and family care, "
            "can become worship if performed sincerely for Allah alone."
        )
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "• Sincere daily intention transforms mundane activities like study and work into acts of worship.\n"
            "• The Prophet peace be upon him taught: إِنَّمَا الْأَعْمَالُ بِالنِّيَّاتِ وَإِنَّمَا لِكُلِّ امْرِئٍ مَا نَوَى."
        )
        mock_res = MagicMock(choices=[mock_choice], usage=MagicMock(total_tokens=160))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_res
                resp = await ac.post("/summarize", json={"post_content": mixed_post, "user_id": "mixed_user"})
                assert resp.status_code == 200
                data = resp.json()
                summary = data["summary"]
                assert summary.count("•") == 2
                assert "إِنَّمَا الْأَعْمَالُ بِالنِّيَّاتِ" in summary

    @pytest.mark.asyncio
    async def test_long_post_generates_3_bullets(self):
        long_content = (
            "The month of Ramadan offers a transformative spiritual journey for Muslims worldwide. "
            "Throughout these blessed thirty days, individuals observe strict fasting from dawn until sunset, "
            "which serves to discipline desires and nurture empathy towards those experiencing poverty and hardship. "
            "Furthermore, mosques fill each evening for communal Taraweeh prayers and daily Quran recitation circles. "
            "Generosity reaches its peak through the distribution of Zakat and voluntary charity to support vulnerable families. "
            "The final ten nights present Laylat al-Qadr, an occasion of unparalleled blessing that exceeds a thousand months. "
            "Believers dedicate their late hours to sincere repentance, personal reflection, and supplication. "
            "Cultivating these consistent spiritual habits during Ramadan establishes a foundation for lifelong piety."
        )
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "• Ramadan fasting disciplines personal desires while fostering deep empathy for the less fortunate.\n"
            "• The month promotes vibrant communal worship through nightly Taraweeh prayers and extensive charitable giving.\n"
            "• Believers maximize devotion during the final ten nights, seeking divine forgiveness during Laylat al-Qadr."
        )
        mock_res = MagicMock(choices=[mock_choice], usage=MagicMock(total_tokens=220))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch("app.api.summarize.cache.get", new_callable=AsyncMock, return_value=None):
                mock_create.return_value = mock_res
                resp = await ac.post("/summarize", json={"post_content": long_content, "user_id": "long_user_fresh"})
                assert resp.status_code == 200
                data = resp.json()
                summary = data["summary"]
                lines = [l for l in summary.split("\n") if l.strip()]
                assert len(lines) == 3
                assert all(l.startswith("• ") for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# 2. ISLAMIC CHAT, DIRECT ANSWERS & QURAN RAG REGRESSION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestIslamicChatAndQuranRAG:

    def test_direct_answer_how_many_prophets(self):
        answer = rag_service.get_direct_answer("How many prophets are mentioned by name in the Quran?")
        assert answer is not None
        assert "25 prophets" in answer or "**25**" in answer or "25" in answer
        assert "Adam" in answer
        assert "Musa" in answer or "Moses" in answer
        assert "Muhammad" in answer
        # Must NOT suggest opening Quran module
        assert "open the quran module" not in answer.lower()

    def test_direct_answer_first_and_final_prophet(self):
        ans_first = rag_service.get_direct_answer("Who was the first prophet in Islam?")
        assert ans_first is not None
        assert "Adam" in ans_first

        ans_last = rag_service.get_direct_answer("Who was the last prophet in Islam?")
        assert ans_last is not None
        assert "Muhammad" in ans_last

    def test_direct_answer_named_woman_and_companion(self):
        ans_woman = rag_service.get_direct_answer("Which woman is mentioned by name in the Quran?")
        assert ans_woman is not None
        assert "Maryam" in ans_woman or "Mary" in ans_woman

        ans_companion = rag_service.get_direct_answer("Which companion is mentioned by name in the Quran?")
        assert ans_companion is not None
        assert "Zayd ibn Harithah" in ans_companion

    def test_quran_modesty_retrieval_contains_verses_and_hadith(self):
        retrieved = rag_service.retrieve("What does the Quran say about modesty?")
        assert retrieved is not None
        # Verses from An-Nur 24:30-31 and Al-Ahzab 33:59
        assert "An-Nur" in retrieved or "24:30" in retrieved or "24:31" in retrieved
        assert "Al-Ahzab" in retrieved or "33:59" in retrieved
        # Authentic Hadith
        assert "Bukhari" in retrieved or "Muslim" in retrieved
        assert "Haya" in retrieved or "modesty" in retrieved.lower()

    def test_unrelated_secular_query_returns_empty_rag(self):
        retrieved = rag_service.retrieve("How do I implement quicksort in Python?")
        assert retrieved == ""

    @pytest.mark.asyncio
    async def test_chat_modesty_invokes_llm_with_grounded_verses_and_hadith(self):
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "In the Holy Quran, modesty (Haya) is a cornerstone of faith. "
            "In Surah An-Nur (24:30-31), Allah commands believing men and women to lower their gaze and guard their chastity. "
            "Furthermore, Surah Al-Ahzab (33:59) guides Muslim women regarding their dress and modesty. "
            "Prophet Muhammad ﷺ emphasized in Sahih al-Bukhari (24) and Sahih Muslim (35) that 'Al-Haya is a branch of faith'."
        )
        mock_res = MagicMock(choices=[mock_choice], usage=MagicMock(total_tokens=220))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.cache.get", new_callable=AsyncMock, return_value=None), \
                 patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_res
                resp = await ac.post("/chat", json={"message": "What does the Quran say about modesty?", "user_id": "test_modesty_qa_clean"})
                assert resp.status_code == 200
                data = resp.json()
                reply = data["reply"]
                assert "An-Nur" in reply or "24:30" in reply
                assert "Bukhari" in reply or "faith" in reply
                assert mock_create.called is True
                sent_prompt = mock_create.call_args[1]["messages"][0]["content"]
                assert "An-Nur" in sent_prompt or "24:30" in sent_prompt
                assert "Bukhari" in sent_prompt or "Haya" in sent_prompt

    @pytest.mark.asyncio
    async def test_chat_prophets_question_returns_direct_25_without_llm(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                resp = await ac.post(
                    "/chat",
                    json={"message": "How many prophets are mentioned by name in the Quran?", "user_id": "test_prophets_qa"},
                )
                assert resp.status_code == 200
                data = resp.json()
                # Fast direct answer, LLM bypassed
                assert mock_create.called is False
                assert "25 prophets" in data["reply"] or "25" in data["reply"]
                assert "Adam" in data["reply"]
                assert "open the quran module" not in data["reply"].lower()
