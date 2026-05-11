import ast
import difflib
import json
import logging
import os
import re
from typing import Optional

# ── Constants / Maps ──────────────────────────────────────────────────────────
_STOP_WORDS: set[str] = {
    "what", "does", "the", "quran", "say", "about", "in", "islam",
    "islamic", "view", "on", "according", "to", "i", "want", "know",
    "tell", "me", "show", "how", "can", "do", "is", "it", "a", "an",
    "and", "or", "of", "for", "from", "with", "that", "this", "are",
    "was", "were", "be", "been", "by", "at", "as", "up", "if", "so",
    "he", "she", "they", "we", "you", "his", "her", "its", "their",
    "my", "your", "all", "any", "not", "no", "but", "had", "has",
    "have", "will", "would", "could", "should", "may", "might",
    "allah", "prophet", "surah", "verse", "ayat", "ayah",
    "step", "please", "give", "verses", "ruling", "get",
}

_TRANSLIT: dict[str, str] = {
    "sabr":        "patience",
    "shukr":       "gratitude thankfulness",
    "tawakkul":    "trust reliance",
    "taqwa":       "righteousness piety God-consciousness",
    "iman":        "faith belief",
    "kufr":        "disbelief",
    "shirk":       "polytheism associating partners",
    "zulm":        "oppression wrongdoing injustice",
    "adl":         "justice fairness",
    "ilm":         "knowledge",
    "hikmah":      "wisdom",
    "rizq":        "provision sustenance",
    "amanah":      "trust responsibility",
    "riba":        "interest usury",
    "khamr":       "alcohol wine intoxicants",
    "zakat":       "charity alms purification",
    "sadaqah":     "charity voluntary giving",
    "jihad":       "striving struggle effort",
    "tawbah":      "repentance return",
    "istighfar":   "forgiveness seeking pardon",
    "jannah":      "paradise garden heaven",
    "jahannam":    "hell hellfire punishment",
    "dajjal":      "antichrist false messiah",
    "firaun":      "pharaoh",
    "musa":        "moses",
    "isa":         "jesus",
    "ibrahim":     "abraham",
    "nuh":         "noah",
    "yusuf":       "joseph",
    "dawud":       "david",
    "sulayman":    "solomon",
    "jiran":       "neighbors",
    "aurat":       "women woman",
    "huqooq":      "rights",
    "nifaq":       "hypocrisy",
    "munafiq":     "hypocrite",
    "tawadu":      "humility",
    "kibr":        "arrogance pride",
    "hasad":       "envy jealousy",
    "ghayba":      "backbiting",
    "namima":      "tale-bearing slander",
    "siddiq":      "truthful honest",
    "tawasul":     "intercession",
    "barzakh":     "intermediate realm afterlife",
    "qiyamah":     "resurrection judgment day",
    "mizan":       "scale balance",
    "sirat":       "path bridge",
    "qadar":       "destiny divine decree",
    "tawhid":      "monotheism oneness",
    "risalah":     "prophethood message",
    "akhirah":     "hereafter afterlife",
    "dunya":       "world worldly life",
    "nikah":       "marriage",
    "talaq":       "divorce",
    "wasiyah":     "will inheritance",
    "hudud":       "prescribed punishments",
    "halal":       "permissible lawful",
    "haram":       "forbidden prohibited",
    "makruh":      "disliked",
    "wajib":       "obligatory",
    "sunnah":      "prophetic tradition",
    "bidah":       "innovation",
    "ibadat":      "worship",
    "muamalat":    "dealings transactions",
}

_SURAH_SPELLING_MAP: dict[str, str] = {
    "akhlas":      "ikhlas",
    "ikhlaas":     "ikhlas",
    "al-ikhlas":   "al ikhlas",
    "yassin":      "yasin",
    "yaseen":      "yasin",
    "ya-seen":     "yasin",
    "yaasin":      "yasin",
    "fateha":      "fatihah",
    "fatiha":      "fatihah",
    "al-fatiha":   "al fatihah",
    "baqara":      "baqarah",
    "al-baqarah":  "al baqarah",
    "al-kahf":     "al kahf",
    "al-mulk":     "al mulk",
    "an-nas":      "an nas",
    "naas":        "nas",
    "al-falaq":    "al falaq",
    "noor":        "light",
    "nur":         "light",
    "imran":       "ali imran",
    "ankabut":     "al ankabut",
    "al-ankabut":  "al ankabut",
    "maidah":      "al maidah",
    "al-maidah":   "al maidah",
    "nisa":        "an nisa",
    "al-nisa":     "an nisa",
    "taubah":      "at tawbah",
    "towba":       "at tawbah",
}

_APP_TERMS: set[str] = {
    "siratsync", "app", "feature", "features", "developer", "kaiser",
    "prayer", "habit", "tracker", "community", "hadith", "quran",
    "qibla", "tasbih", "ramadan", "salah", "namaz", "offline",
}

logger = logging.getLogger(__name__)

# ── Helper Functions ─────────────────────────────────────────────────────────
def _expand_query(query_lower: str) -> str:
    expanded = query_lower
    for term, expansion in _TRANSLIT.items():
        if term in query_lower:
            expanded = f"{expanded} {expansion}"
    return expanded

def _meaningful_words(text: str) -> set[str]:
    return {w for w in text.split() if w not in _STOP_WORDS and len(w) > 2}

# ── RAGKnowledge Class ──────────────────────────────────────────────────────
class RAGKnowledge:
    """
    RAG engine for SiratSync.
    Combines a JSON knowledge-base (app info, duas, FAQs …)
    with a full Quran index (quran_indexed_final.json).
    """

    def __init__(
        self,
        kb_path: str = "knowledge.json",
        quran_index_path: str = "quran_indexed_final.json",
    ):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Adjust path to data directory
        data_dir = os.path.join(current_dir, "..", "data")

        self.conversation_context: dict[str, dict] = {}

        kb_full = os.path.join(data_dir, kb_path)
        with open(kb_full, "r", encoding="utf-8") as f:
            self.knowledge: dict = json.load(f)

        total = sum(
            len(v) if isinstance(v, list) else 1
            for v in self.knowledge.values()
        )
        logger.info(f"✅ Knowledge base loaded — {total} items")

        self.quran_index_path = os.path.join(data_dir, quran_index_path)
        self.quran_data: Optional[list] = None

        self.search_index = self._build_search_index()

    def _get_user_context(self, user_id: str) -> dict:
        if user_id not in self.conversation_context:
            self.conversation_context[user_id] = {
                "last_surah_id":   None,
                "last_surah_name": None,
                "last_verse_id":   None,
            }
        return self.conversation_context[user_id]

    # ── Quran loading ──────────────────────────────────────────────────────────
    def _load_quran_data(self) -> None:
        if self.quran_data is not None:
            return
        try:
            with open(self.quran_index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.quran_data = data.get("quran", [])
            logger.info(f"📖 Quran loaded — {len(self.quran_data)} surahs")

            self._surah_by_id = {s["id"]: s for s in self.quran_data}
            self._surah_by_name = {}
            for s in self.quran_data:
                for alias in s.get("_metadata", {}).get("surah_names", []):
                    self._surah_by_name[alias.lower()] = s
        except FileNotFoundError:
            logger.error(f"❌ Quran index not found: {self.quran_index_path}")
            self.quran_data = []
        except Exception as exc:
            logger.error(f"❌ Quran load error: {exc}")
            self.quran_data = []

    # ── Knowledge-base search index ────────────────────────────────────────────
    def _build_search_index(self) -> list[dict]:
        index = []
        for category, items in self.knowledge.items():
            if isinstance(items, list):
                for item in items:
                    text = self._extract_text(item)
                    index.append({
                        "category":    category,
                        "item":        item if isinstance(item, dict) else {"content": item},
                        "search_text": text.lower(),
                        "keywords":    set(text.lower().split()),
                    })
            elif isinstance(items, dict):
                text = self._extract_text(items)
                index.append({
                    "category":    category,
                    "item":        items,
                    "search_text": text.lower(),
                    "keywords":    set(text.lower().split()),
                })
        return index

    @staticmethod
    def _extract_text(obj) -> str:
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            parts = []
            for v in obj.values():
                if isinstance(v, str):
                    parts.append(v)
                elif isinstance(v, list):
                    parts.extend(str(x) for x in v)
            return " ".join(parts)
        return str(obj)

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLIC: list_categories
    # ═════════════════════════════════════════════════════════════════════════
    def list_categories(self) -> list[str]:
        return list(self.knowledge.keys())

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLIC: retrieve  (feeds {knowledge} in the system prompt)
    # ═════════════════════════════════════════════════════════════════════════
    def retrieve(self, query: str, top_k: int = 4) -> str:
        self._load_quran_data()
        q  = query.strip()
        ql = q.lower()

        direct = self.get_direct_answer(q)
        if direct:
            return direct

        nickname_result = self._check_verse_nicknames(ql)
        if nickname_result:
            return nickname_result

        followup = self._handle_followup(q, ql, user_id="default")
        if followup:
            return followup

        # ✅ FIX 1: Handle "surah <name> verse <num>" pattern
        snv_name = re.search(
            r"(?:surah|surat)\s+([a-z][\w\s\-]{1,30}?)\s+(?:verse|ayat|ayah)\s+(\d{1,3})\b",
            ql,
        )
        if snv_name:
            candidate = _SURAH_SPELLING_MAP.get(snv_name.group(1).strip(), snv_name.group(1).strip())
            surah = self.get_surah_by_name(candidate)
            if surah:
                self._update_surah_context(surah, user_id="default")
                return self._handle_verse_reference_query(surah["id"], int(snv_name.group(2)))

        verse_ref = self._extract_verse_ref(ql)
        if verse_ref:
            sid, vid = verse_ref
            return self._handle_verse_reference_query(sid, vid)

        snv = re.search(
            r"(?:surah|surat|chapter)\s+([a-z\s\-]+?)\s+(?:verse|ayat|ayah)\s+(\d+)",
            ql,
        )
        if snv:
            surah = self.get_surah_by_name(snv.group(1).strip())
            if surah:
                self._update_surah_context(surah, user_id="default")
                return self._handle_verse_reference_query(surah["id"], int(snv.group(2)))

        snum = re.search(r"\bsurah\s+(\d{1,3})\b", ql)
        if snum:
            sid = int(snum.group(1))
            if 1 <= sid <= 114:
                for s in self.quran_data:
                    if s.get("id") == sid:
                        self._update_surah_context(s, user_id="default")
                        return self._handle_surah_summary_query(s.get("name_en", ""))

        plain_surah = re.search(r"^(?:surah|surat)\s+([a-z]+(?:[\s\-][a-z]+)*)$", ql.strip())
        if plain_surah:
            candidate = _SURAH_SPELLING_MAP.get(plain_surah.group(1).strip(), plain_surah.group(1).strip())
            result = self._handle_surah_summary_query(candidate)
            if "couldn't find" not in result:
                return result

        juz_r = self._handle_juz_query(ql)
        if juz_r:
            return juz_r

        stats_r = self._handle_stats_query(ql)
        if stats_r:
            return stats_r

        SURAH_PATS = [
            r"(?:tell me about|what is|explain|summary of|meaning of|"
            r"benefits of|tafsir of|show me|open|read|info about|"
            r"information about)\s+surah\s+([a-z]+(?:[\s\-][a-z]+)*)",
            r"surah\s+([a-z]+(?:[\s\-][a-z]+)*)\s+"
            r"(?:summary|meaning|tafsir|info|benefits|explain|details)",
        ]
        for pat in SURAH_PATS:
            m = re.search(pat, ql)
            if m:
                candidate = _SURAH_SPELLING_MAP.get(m.group(1).strip(), m.group(1).strip())
                result = self._handle_surah_summary_query(candidate)
                if "couldn't find" not in result:
                    return result

        if self._is_quran_topic_query(ql):
            return self._handle_quran_topic_query(q)

        for faq_key in ("faqs", "faqs_new"):
            for faq in self.knowledge.get(faq_key, []):
                fq = faq.get("question", "").lower()
                if fq in ql or ql in fq:
                    return f"❓ {faq['answer']}"

        return self._keyword_fallback(ql, top_k)

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLIC: get_rag_data_for_llm
    # ═════════════════════════════════════════════════════════════════════════
    def get_rag_data_for_llm(self, query: str, user_id: str = "default") -> Optional[str]:
        self._load_quran_data()
        ql = query.lower().strip()

        verse_ref = self._extract_verse_ref(ql)
        if verse_ref:
            sid, vid = verse_ref
            v = self.get_verse_by_reference(sid, vid)
            if v:
                ctx = self._get_user_context(user_id)
                ctx["last_surah_id"]   = sid
                ctx["last_surah_name"] = v["surah_name"]
                ctx["last_verse_id"]   = vid
        
        snum_match = re.search(r'\bsurah\s+(\d{1,3})\b', ql)
        if snum_match:
            sid = int(snum_match.group(1))
            if 1 <= sid <= 114:
                surah = self.get_surah_by_id(sid)
                if surah:
                    self._update_surah_context(surah)
                    summary = self.get_surah_summary(surah.get('name_en', ''))
                    if summary:
                        return self._format_surah_for_llm(summary)

        surah_name = self._extract_surah_name(ql)
        if surah_name:
            summary = self.get_surah_summary(surah_name)
            if summary:
                self._update_surah_context({"id": summary["id"], "name_en": summary["name"]})
                return self._format_surah_for_llm(summary)

        result = self.search_quran_by_topic(query)
        if result.get("verses") or result.get("surahs"):
            return self._format_topic_result_for_llm(result)

        return None

    def _extract_surah_name(self, ql: str) -> Optional[str]:
        patterns = [
            r"(?:tell me about|what is|explain|summary of|meaning of|"
            r"benefits of|tafsir of|show me|open|read|about|info on|"
            r"information about)\s+surah\s+([a-z]+(?:[\s\-][a-z]+)*)",
            r"(?:surah|surat|chapter)\s+([a-z]+(?:[\s\-][a-z]+)*)",
        ]
        for pat in patterns:
            m = re.search(pat, ql)
            if m:
                candidate = m.group(1).strip()
                if candidate.isdigit():
                    return None
                if candidate in _APP_TERMS or any(t in candidate for t in _APP_TERMS):
                    return None
                candidate = _SURAH_SPELLING_MAP.get(candidate, candidate)
                if self.get_surah_by_name(candidate):
                    return candidate
        return None

    # ── LLM data formatters ────────────────────────────────────────────────────
    def _format_verse_for_llm(self, v: dict) -> str:
        lines = [
            f"VERSE REFERENCE: {v['surah_name']} ({v['surah_translation']}) {v['surah_id']}:{v['verse_id']}",
            f"ARABIC: {v['arabic']}",
            f"ENGLISH: {v['english']}",
        ]
        if v.get("transliteration"):
            lines.append(f"TRANSLITERATION: {v['transliteration']}")
        if v.get("urdu"):
            lines.append(f"URDU: {v['urdu']}")
        if v.get("kashmiri"):
            ks = v["kashmiri"]
            lines.append(f"KASHMIRI TAFSIR: {ks[:600]}{'...' if len(ks) > 600 else ''}")
        similar = self.get_similar_ayahs(v["surah_id"], v["verse_id"], top_n=2, min_score=50)
        if similar:
            lines.append("\nSIMILAR VERSES:")
            for sv in similar:
                lines.append(
                    f"  - {sv['surah_name']} {sv['surah_id']}:{sv['verse_id']}: {sv['english'][:200]}"
                )
        return "\n".join(lines)

    def _format_surah_for_llm(self, s: dict) -> str:
        lines = [
            f"SURAH: {s['name']} ({s['translation']}) — Arabic: {s['arabic']}",
            f"SURAH NUMBER: {s['id']}",
            f"VERSES: {s['verse_count']} | WORDS: {s['words']} | LETTERS: {s['letters']}",
            f"REVELATION TYPE: {s['revelation_type'].capitalize()}",
            f"JUZ: {s.get('juz', 'N/A')}",
            f"SUMMARY: {s['summary']}",
            f"MAIN TOPICS: {', '.join(s['main_topics'][:6])}",
            f"KEYWORDS: {', '.join(s['keywords'][:8])}",
            f"FIRST VERSE (Arabic): {s['first_verse_arabic']}",
            f"FIRST VERSE (English): {s['first_verse_english']}",
        ]
        if s.get("first_verse_urdu"):
            lines.append(f"FIRST VERSE (Urdu): {s['first_verse_urdu']}")
        return "\n".join(lines)

    def _format_topic_result_for_llm(self, result: dict) -> str:
        lines = []
        surahs = result.get("surahs", [])
        verses = result.get("verses", [])

        if surahs:
            lines.append("RELATED SURAHS:")
            for s in surahs[:2]:
                meta = s.get("_metadata", {})
                lines.append(
                    f"  - {s.get('name_en')} ({s.get('name_translation')}): "
                    f"{', '.join(meta.get('main_topics', [])[:3])}"
                )

        if verses:
            lines.append("\nVERSES:")
            for v in verses[:4]:
                lines.append(
                    f"\nVERSE: {v['surah_name']} ({v['surah_translation']}) "
                    f"{v['surah_id']}:{v['verse_id']}"
                )
                lines.append(f"ARABIC: {v['arabic']}")
                lines.append(f"ENGLISH: {v['english']}")
                if v.get("urdu"):
                    lines.append(f"URDU: {v['urdu']}")
                if v.get("kashmiri"):
                    ks = v["kashmiri"]
                    lines.append(f"KASHMIRI: {ks[:400]}{'...' if len(ks) > 400 else ''}")

        return "\n".join(lines) if lines else ""

    # ═════════════════════════════════════════════════════════════════════════
    # QURAN: surah lookup
    # ═════════════════════════════════════════════════════════════════════════
    def get_surah_by_name(self, name: str) -> Optional[dict]:
        self._load_quran_data()
        if not self.quran_data:
            return None

        name_lower = re.sub(r"^(surah|surat|chapter)\s+", "", name.lower().strip())
        name_lower = _SURAH_SPELLING_MAP.get(name_lower, name_lower)

        for s in self.quran_data:
            meta = s.get("_metadata", {})
            if (name_lower == s.get("name_en", "").lower()
                    or name_lower == s.get("name_translation", "").lower()):
                return s
            for sn in meta.get("surah_names", []):
                if name_lower == sn.lower():
                    return s

        for s in self.quran_data:
            meta = s.get("_metadata", {})
            if (name_lower in s.get("name_en", "").lower()
                    or name_lower in s.get("name_translation", "").lower()):
                return s
            for sn in meta.get("surah_names", []):
                if name_lower in sn.lower() or sn.lower() in name_lower:
                    return s

        name_tokens = set(re.split(r"[\s\-]+", name_lower))
        best_surah, best_overlap = None, 0
        for s in self.quran_data:
            meta = s.get("_metadata", {})
            all_names = (
                [s.get("name_en", ""), s.get("name_translation", "")]
                + meta.get("surah_names", [])
            )
            for sn in all_names:
                sn_tokens = set(re.split(r"[\s\-]+", sn.lower()))
                overlap   = len(name_tokens & sn_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_surah   = s
        if best_overlap >= 1:
            return best_surah

        best_surah_ed, best_ratio = None, 0.0
        for s in self.quran_data:
            meta = s.get("_metadata", {})
            all_names = (
                [s.get("name_en", ""), s.get("name_translation", "")]
                + meta.get("surah_names", [])
            )
            for sn in all_names:
                if not sn:
                    continue
                ratio = difflib.SequenceMatcher(None, name_lower, sn.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio    = ratio
                    best_surah_ed = s
        if best_ratio >= 0.75:
            return best_surah_ed

        return None

    def get_surah_by_id(self, surah_id: int) -> Optional[dict]:
        self._load_quran_data()
        for s in self.quran_data:
            if s.get("id") == surah_id:
                return s
        return None

    def get_surah_summary(self, surah_name: str) -> Optional[dict]:
        surah = self.get_surah_by_name(surah_name)
        if not surah:
            return None
        meta        = surah.get("_metadata", {})
        first_verse = surah.get("array", [{}])[0] if surah.get("array") else {}
        return {
            "id":                  surah.get("id"),
            "name":                surah.get("name_en", ""),
            "translation":         surah.get("name_translation", ""),
            "arabic":              surah.get("name", ""),
            "type":                surah.get("type_en", "unknown"),
            "summary":             meta.get("summary", ""),
            "keywords":            meta.get("keywords_en", [])[:8],
            "main_topics":         meta.get("main_topics", []),
            "verse_count":         meta.get("verse_count", len(surah.get("array", []))),
            "revelation_type":     meta.get("revelation_type", surah.get("type_en", "unknown")),
            "juz":                 meta.get("juz"),
            "surah_names":         meta.get("surah_names", []),
            "first_verse_arabic":  first_verse.get("ar", ""),
            "first_verse_english": first_verse.get("en", ""),
            "first_verse_urdu":    first_verse.get("ur", ""),
            "words":               surah.get("words", 0),
            "letters":             surah.get("letters", 0),
        }

    # ═════════════════════════════════════════════════════════════════════════
    # QURAN: verse retrieval
    # ═════════════════════════════════════════════════════════════════════════
    def get_verse_by_reference(self, surah_id: int, verse_id: int) -> Optional[dict]:
        self._load_quran_data()
        for surah in self.quran_data:
            if surah.get("id") == surah_id:
                for v in surah.get("array", []):
                    if v.get("id") == verse_id:
                        return {
                            "surah_id":          surah.get("id"),
                            "surah_name":        surah.get("name_en", ""),
                            "surah_translation": surah.get("name_translation", ""),
                            "surah_arabic":      surah.get("name", ""),
                            "verse_id":          v.get("id"),
                            "arabic":            v.get("ar", ""),
                            "english":           v.get("en", ""),
                            "urdu":              v.get("ur", ""),
                            "kashmiri":          v.get("ks", ""),
                            "transliteration":   v.get("transliteration", ""),
                            "similar_ayahs":     v.get("similar_ayahs", []),
                        }
        return None

    def get_verse_by_key(self, key: str) -> Optional[dict]:
        try:
            sid, vid = key.split(":")
            return self.get_verse_by_reference(int(sid), int(vid))
        except Exception:
            return None

    def get_similar_ayahs(
        self,
        surah_id: int,
        verse_id: int,
        top_n: int = 3,
        min_score: int = 40,
    ) -> list[dict]:
        self._load_quran_data()
        source = self.get_verse_by_reference(surah_id, verse_id)
        if not source:
            return []

        raw_similar = source.get("similar_ayahs", [])
        filtered    = [s for s in raw_similar if s.get("score", 0) >= min_score]
        sorted_sim  = sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)

        results = []
        for s in sorted_sim[:top_n]:
            ref = s.get("matched_ayah_key", "")
            v   = self.get_verse_by_key(ref)
            if v:
                v["similarity_score"]    = s.get("score", 0)
                v["similarity_coverage"] = s.get("coverage", 0)
                v["matched_words"]       = s.get("matched_words_count", 0)
                results.append(v)
        return results

    # ═════════════════════════════════════════════════════════════════════════
    # QURAN: topic search
    # ═════════════════════════════════════════════════════════════════════════
    def search_quran_by_topic(self, query: str) -> dict:
        self._load_quran_data()
        if not self.quran_data:
            return {"surahs": [], "verses": []}

        ql       = query.lower()
        expanded = _expand_query(ql)
        mw       = _meaningful_words(expanded)
        KNOWN_VERSE_MAPPINGS = {
            # ── Relationship & Family ──────────────────────────────────────
            "rights of sisters":  [(4, 11), (4, 12), (4, 176), (4, 7)],
            "sisters rights":     [(4, 11), (4, 12), (4, 176), (4, 7)],
            "rights of women":    [(4, 19), (4, 32), (4, 34), (2, 228)],
            "women rights":       [(4, 19), (4, 32), (4, 34), (2, 228)],
            "women":              [(4, 19), (4, 34), (2, 228), (33, 35)],
            "inheritance":        [(4, 11), (4, 12), (4, 176), (2, 180), (4, 7)],
            "rights of parents":  [(17, 23), (17, 24), (31, 14), (46, 15)],
            "parents":            [(17, 23), (17, 24), (31, 14), (46, 15)],
            "mother":             [(17, 23), (31, 14), (46, 15)],
            "father":             [(17, 23), (17, 24), (31, 14)],
            "rights of children": [(4, 11), (6, 151), (17, 31)],
            "children":           [(4, 11), (6, 151), (17, 31), (2, 233)],
            "marriage in islam":  [(4, 3), (4, 4), (30, 21), (24, 32)],
            "marriage":           [(4, 3), (30, 21), (24, 32), (2, 221)],
            "nikah":              [(4, 3), (30, 21), (24, 32), (2, 221)],
            "divorce":            [(2, 226), (2, 227), (65, 1), (65, 2)],
            "talaq":              [(2, 226), (2, 227), (65, 1), (65, 2)],
            "husband":            [(4, 34), (2, 228), (30, 21)],
            "wife":               [(4, 34), (2, 228), (30, 21), (4, 19)],
            "family":             [(17, 23), (4, 1), (30, 21), (2, 233)],
            # ── Worship & Practice ────────────────────────────────────────
            "forgiveness":        [(39, 53), (3, 135), (4, 110), (42, 25)],
            "repentance":         [(39, 53), (3, 135), (4, 110), (2, 222)],
            "patience":           [(2, 155), (2, 156), (2, 157), (3, 200)],
            "sabr":               [(2, 155), (2, 156), (2, 157), (3, 200)],
            "gratitude":          [(14, 7), (2, 152), (31, 12)],
            "shukr":              [(14, 7), (2, 152), (31, 12)],
            "prayer":             [(2, 43), (2, 238), (4, 103), (29, 45)],
            "salah":              [(2, 43), (2, 238), (4, 103), (29, 45)],
            "fasting":            [(2, 183), (2, 184), (2, 185), (2, 187)],
            "ramadan":            [(2, 183), (2, 185), (2, 187)],
            "zakat":              [(2, 43), (2, 110), (9, 60)],
            "charity":            [(2, 261), (2, 262), (2, 263), (2, 264), (2, 271)],
            "sadaqah":            [(2, 261), (2, 271), (2, 274)],
            "hajj":               [(2, 196), (2, 197), (3, 97)],
            # ── Ethics & Character ────────────────────────────────────────
            "justice":            [(4, 58), (4, 135), (5, 8), (16, 90)],
            "honesty":            [(2, 42), (33, 70), (4, 135)],
            "backbiting":         [(49, 12), (104, 1)],
            "lying":              [(9, 119), (33, 70), (2, 42)],
            "arrogance":          [(31, 18), (16, 23), (7, 13)],
            "pride":              [(31, 18), (16, 23), (57, 23)],
            "humility":           [(31, 18), (25, 63), (17, 37)],
            "envy":               [(113, 5), (4, 54), (2, 109)],
            "knowledge":          [(20, 114), (58, 11), (39, 9)],
            "wisdom":             [(2, 269), (31, 12), (17, 39)],
            "trust in allah":     [(65, 3), (3, 160), (39, 38)],
            "tawakkul":           [(65, 3), (3, 160), (39, 38)],
            # ── Forbidden Things ─────────────────────────────────────────
            "riba":               [(2, 275), (2, 276), (2, 278), (3, 130)],
            "interest":           [(2, 275), (2, 276), (2, 278), (3, 130)],
            "alcohol":            [(2, 219), (4, 43), (5, 90), (5, 91)],
            "khamr":              [(2, 219), (4, 43), (5, 90), (5, 91)],
            "hijab":              [(24, 30), (24, 31), (33, 59)],
            "modesty":            [(24, 30), (24, 31), (33, 59)],
            # ── Neighbors & Society ───────────────────────────────────────
            "neighbors":          [(4, 36)],
            "orphans":            [(4, 6), (4, 10), (93, 9)],
            # ── Afterlife ─────────────────────────────────────────────────
            "paradise":           [(55, 46), (3, 133), (76, 12)],
            "jannah":             [(55, 46), (3, 133), (76, 12)],
            "hellfire":           [(2, 24), (14, 17), (38, 55)],
            "jahannam":           [(2, 24), (14, 17), (38, 55)],
            "death":              [(3, 185), (4, 78), (62, 8)],
            "judgment day":       [(82, 1), (99, 1), (2, 281)],
            "qiyamah":            [(82, 1), (99, 1), (2, 281)],
        }
        
        best_key_match = None
        best_key_len   = 0
        for key in KNOWN_VERSE_MAPPINGS:
            if key in ql and len(key) > best_key_len:
                best_key_len   = len(key)
                best_key_match = key

        if best_key_match:
            priority_verses = []
            for sid, vid in KNOWN_VERSE_MAPPINGS[best_key_match]:
                verse = self.get_verse_by_reference(sid, vid)
                if verse:
                    verse["relevance_score"] = 100
                    priority_verses.append(verse)
            if priority_verses:
                return {"surahs": [], "verses": priority_verses}

        surah_scores: list[tuple[float, dict]] = []

        for surah in self.quran_data:
            meta  = surah.get("_metadata", {})
            score = 0.0

            for verse_key, nicknames in meta.get("verse_nicknames", {}).items():
                for nn in nicknames:
                    if nn.lower() in expanded:
                        score += 30

            for cq in meta.get("common_queries", []):
                cq_l = cq.lower()
                if cq_l in expanded or expanded in cq_l:
                    score += 25
                elif any(w in cq_l for w in mw):
                    score += 10

            for topic in meta.get("main_topics", []):
                tl = topic.lower()
                if tl in expanded:
                    score += 18
                elif any(w in tl for w in mw):
                    score += 10

            for sn in meta.get("surah_names", []):
                if sn.lower() in expanded:
                    score += 15

            for kw in meta.get("keywords_en", []):
                kw_l = kw.lower().strip()
                if kw_l.startswith("surah "):
                    kw_l = kw_l[6:]
                if not kw_l or kw_l in ("surah", "ayat", "verse", "chapter"):
                    continue
                if kw_l in expanded:
                    score += 12
                    if " " in kw_l:
                        score += 5
                elif any(w in kw_l for w in mw):
                    score += 6

            summary = meta.get("summary", "").lower()
            for w in mw:
                if w in summary:
                    score += 5

            st = meta.get("searchable_text_en", "").lower()
            for w in mw:
                if w in st:
                    score += 2

            if score > 5:
                surah_scores.append((score, surah))

        surah_scores.sort(key=lambda x: x[0], reverse=True)

        all_verses: list[dict] = []

        for surah in self.quran_data:
            meta     = surah.get("_metadata", {})
            meta_kws = {kw.lower() for kw in meta.get("keywords_en", [])}

            for v in surah.get("array", []):
                vs = 0.0
                
                words = ql.split()
                phrases = []
                for i in range(len(words)):
                    for j in range(i+1, len(words)+1):
                        phrase = " ".join(words[i:j])
                        if len(phrase) > 2:
                            phrases.append(phrase)

                for kw in meta_kws:
                    if kw in expanded:
                        vs += 10
                
                for phrase in phrases:
                    for t in v.get("topics", []):
                        tn = (t.get("name") or "").lower()
                        if phrase in tn or tn in phrase:
                            vs += 100
                            break
                
                for t in v.get("topics", []):
                    tn = (t.get("name") or "").lower()
                    td = (t.get("description") or "").lower()
                    combined = f"{tn} {td}"
                    if all(w in combined for w in mw if len(w) > 2):
                        vs += 80
                
                for w in mw:
                    if len(w) < 3:
                        continue
                    for t in v.get("topics", []):
                        tn = (t.get("name") or "").lower()
                        td = (t.get("description") or "").lower()
                        if w in tn:
                            vs += 40
                        elif w in td:
                            vs += 25
                
                en = v.get("en", "").lower()
                combined_text = f"{en}"
                for w in mw:
                    if len(w) < 3:
                        continue
                    if w in combined_text:
                        vs += 10
                
                SEMANTIC_MAP = {
                    "sisters": ["sister", "sibling", "female", "woman", "women"],
                    "brothers": ["brother", "sibling", "male", "men"],
                    "rights": ["right", "entitlement", "share", "inheritance", "portion"],
                    "inheritance": ["inherit", "estate", "heir", "bequest", "legacy"],
                }
                
                for word, expansions in SEMANTIC_MAP.items():
                    if word in ql:
                        for exp in expansions:
                            if exp in combined_text:
                                vs += 15
                
                if vs > 0:
                    matched_topics = []
                    for t in v.get("topics", []):
                        tn = (t.get("name") or "").lower()
                        td = (t.get("description") or "").lower()
                        if any(w in tn or w in td for w in mw if len(w) > 2):
                            matched_topics.append({
                                "id": t.get("id"),
                                "name": t.get("name"),
                                "arabic_name": t.get("arabic_name"),
                                "description": t.get("description", "")[:200],
                            })
                    all_verses.append({
                        "surah_id":          surah.get("id"),
                        "surah_name":        surah.get("name_en", ""),
                        "surah_translation": surah.get("name_translation", ""),
                        "verse_id":          v.get("id"),
                        "arabic":            v.get("ar", ""),
                        "english":           v.get("en", ""),
                        "urdu":              v.get("ur", ""),
                        "kashmiri":          v.get("ks", ""),
                        "transliteration":   v.get("transliteration", ""),
                        "similar_ayahs":     v.get("similar_ayahs", []),
                        "matched_topics":    matched_topics,
                        "relevance_score":   round(vs, 2),
                    })

        all_verses.sort(key=lambda x: x["relevance_score"], reverse=True)

        seen: set[tuple] = set()
        top_verses: list[dict] = []
        for v in all_verses:
            key = (v["surah_id"], v["verse_id"])
            if key not in seen:
                seen.add(key)
                top_verses.append(v)

        return {
            "surahs": [s for _, s in surah_scores[:3]],
            "verses": top_verses[:8],
        }

    # ═════════════════════════════════════════════════════════════════════════
    # INTERNAL HANDLERS
    # ═════════════════════════════════════════════════════════════════════════
    def _is_quran_topic_query(self, ql: str) -> bool:
        EXPLICIT = [
            "what does quran say", "quran says", "quranic verses",
            "ayat about", "verses about", "according to quran", "in quran",
            "what does islam say", "what does islam teach", "islamic view",
            "islamic ruling", "is this haram", "is this halal",
            "permissible in islam", "forbidden in islam", "allah says",
            "quranic guidance", "quran on", "islam on",
            "kashmiri translation", "urdu translation",
            "show me in urdu", "show me in kashmiri",
            "rights of", "rights for", "rights in islam",
        ]
        if any(t in ql for t in EXPLICIT):
            return True

        TOPICS = [
            "marriage", "women", "rights", "justice", "inheritance", "fasting",
            "prayer", "salah", "zakat", "charity", "forgiveness", "patience",
            "parents", "business", "riba", "interest", "modesty", "hijab",
            "alcohol", "khamr", "neighbors", "creation", "jesus", "musa",
            "dajjal", "paradise", "hellfire", "judgment day", "death",
            "honesty", "lying", "backbiting", "knowledge", "wisdom",
            "divorce", "nikah", "wife", "husband", "children",
            "orphan", "widow", "poor", "trade", "usury",
            "sisters", "brothers", "daughter", "son", "family",
            "relatives", "aunt", "uncle", "niece", "nephew",
            "mother", "father", "grandparents", "grandchildren",
            "spouse", "widow", "widower", "heir", "estate",
            "bequest", "will", "testament", "legacy",
        ]
        CTX = [
            "in islam", "in quran", "islamic", "allah says",
            "quran", "allah", "prophet", "according to",
            "surah", "verse", "ayat", "ayah",
            "rights", "ruling", "hukum", "fatwa",
            "halal", "haram", "permissible", "forbidden",
            "muslim", "muslims", "believers", "ummah",
        ]
        
        has_topic = any(t in ql for t in TOPICS)
        has_context = any(c in ql for c in CTX) or any(e in ql for e in EXPLICIT)
        
        if re.search(r'rights?\s+of\s+\w+', ql):
            return True
            
        return has_topic and has_context

    @staticmethod
    def _extract_verse_ref(ql: str) -> Optional[tuple[int, int]]:
        m = re.search(r"\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b", ql)
        if m:
            return int(m.group(1)), int(m.group(2))
        m2 = re.search(
            r"(?:surah|chapter)\s+(\d{1,3})\s+(?:verse|ayat|ayah)\s+(\d{1,3})", ql
        )
        if m2:
            return int(m2.group(1)), int(m2.group(2))
        return None

    def _check_verse_nicknames(self, ql: str) -> Optional[str]:
        self._load_quran_data()
        for surah in self.quran_data:
            meta = surah.get("_metadata", {})
            for verse_key, nicknames in meta.get("verse_nicknames", {}).items():
                for nn in nicknames:
                    if nn.lower() in ql:
                        try:
                            vt = ast.literal_eval(verse_key)
                            return self._handle_verse_reference_query(vt[0], vt[1])
                        except Exception:
                            pass
        return None

    def _handle_followup(self, query: str, ql: str, user_id: str = "default") -> Optional[str]:
        ctx = self._get_user_context(user_id)
        if not ctx["last_surah_id"]:
            return None

        VERSE_FU = [
            r"(?:verse|ayat|ayah)\s+(\d+)",
            r"show me (?:verse|ayat|ayah)\s+(\d+)",
            r"what is (?:verse|ayat|ayah)\s+(\d+)",
            r"verse (\d+) of it",
            r"(\d+)(?:st|nd|rd|th) (?:verse|ayat|ayah)",
        ]
        for pat in VERSE_FU:
            m = re.search(pat, ql)
            if m:
                vid = int(m.group(1))
                return self._handle_verse_reference_query(ctx["last_surah_id"], vid)

        if any(p in ql for p in ["first verse", "opening verse", "beginning verse", "first ayah"]):
            return self._handle_verse_reference_query(ctx["last_surah_id"], 1)

        if any(p in ql for p in ["last verse", "final verse", "last ayah", "ending verse"]):
            surah = self.get_surah_by_id(ctx["last_surah_id"])
            if surah:
                last_vid = len(surah.get("array", []))
                return self._handle_verse_reference_query(ctx["last_surah_id"], last_vid)

        if ctx["last_verse_id"] and any(
            p in ql for p in ["similar", "related verses", "like this verse"]
        ):
            return self._handle_similar_ayahs_query(ctx["last_surah_id"], ctx["last_verse_id"])

        if any(p in ql for p in ["full surah", "entire surah", "whole surah"]):
            return self._handle_surah_summary_query(ctx["last_surah_name"] or "")

        if any(p in ql for p in ["how many verses", "how many ayat", "verse count"]):
            surah = self.get_surah_by_id(ctx["last_surah_id"])
            if surah:
                return (
                    f"📊 **{surah.get('name_en')}** has "
                    f"**{surah.get('_metadata', {}).get('verse_count', len(surah.get('array', [])))}** verses."
                )

        return None

    def _handle_juz_query(self, ql: str) -> Optional[str]:
        m = re.search(r"\b(?:juz|para|parah)\s+(\d{1,2})\b", ql)
        if not m:
            return None
        juz_num = int(m.group(1))
        self._load_quran_data()
        juz_surahs = [
            s for s in self.quran_data
            if s.get("_metadata", {}).get("juz") == juz_num
        ]
        if not juz_surahs:
            return f"📖 No surahs found for Juz {juz_num}."
        lines = [f"📖 **Surahs in Juz {juz_num}:**\n"]
        for s in juz_surahs:
            vc = s.get("_metadata", {}).get("verse_count", len(s.get("array", [])))
            lines.append(
                f"• **{s.get('name_en')}** ({s.get('name_translation')}) "
                f"— {vc} verses | {s.get('type_en', '').capitalize()}"
            )
        return "\n".join(lines)

    def _handle_stats_query(self, ql: str) -> Optional[str]:
        if not any(p in ql for p in [
            "how many words", "how many letters", "how many verses",
            "how many ayat", "word count", "letter count", "verse count",
            "total words", "total letters", "total ayat","longest surah", "longest chapter", "longest surat","longest verse", "longest ayah", "longest ayat", "shortest verse", "shortest ayah", "shortest ayat","most verses surah", "most verses chapter", "surah with most verses",
        ]):
            return None

        self._load_quran_data()
        for s in self.quran_data:
            meta  = s.get("_metadata", {})
            names = (
                [s.get("name_en", "").lower(), s.get("name_translation", "").lower()]
                + [n.lower() for n in meta.get("surah_names", [])]
            )
            if any(n and n in ql for n in names):
                vc = meta.get("verse_count", len(s.get("array", [])))
                return (
                    f"📊 **{s.get('name_en')} ({s.get('name_translation')})**\n"
                    f"• Verses (Ayat): **{vc}**\n"
                    f"• Words: **{s.get('words', 'N/A')}**\n"
                    f"• Letters: **{s.get('letters', 'N/A')}**\n"
                    f"• Revelation: **{s.get('type_en', '').capitalize()}**\n"
                    f"• Juz: **{meta.get('juz', 'N/A')}**"
                )
        
        if any(p in ql for p in ["longest surah", "longest chapter", "longest surat","most verses surah","most verses chapter","surah with most verses"]):
            longest = max(self.quran_data, key=lambda s: len(s.get("array", [])))
            vc = longest.get("_metadata", {}).get("verse_count", len(longest.get("array", [])))
            return (
                f"📊 **Longest Surah: {longest.get('name_en')} ({longest.get('name_translation')})**\n\n"
                f"📖 **Surah Al-Baqarah (The Cow)** is widely recognized in Islamic scholarship as the longest chapter of "
                f"the Holy Quran. Revealed in Madinah, it is also the second surah in the mushaf order. "
                f"It encompasses a wide range of legal, theological, and moral teachings, including rulings on "
                f"prayer, fasting, charity (zakah), pilgrimage (Hajj), marriage, divorce, and financial transactions.\n\n"
                f"📜 **Notable Verses:**\n"
                f"• **Ayat al-Kursi (2:255)** — The Verse of the Throne, describing Allah's majesty\n"
                f"• **Ayat al-Dayn (2:282)** — The longest single verse in the Quran\n\n"
                f"📊 **Statistics:**\n"
                f"• Verses (Ayat): **{vc}**\n"
                f"• Words: **{longest.get('words', 'N/A'):,}**\n"
                f"• Letters: **{longest.get('letters', 'N/A'):,}**\n"
                f"• Revelation: **{longest.get('type_en', '').capitalize()}**\n"
                f"• Juz: **{longest.get('_metadata', {}).get('juz', 'N/A')}**\n\n"
                f"📌 _Surah Al-Baqarah spans approximately 2.5 Juz (parts)._"
            )

        if any(p in ql for p in ["longest verse", "longest ayah", "longest ayat"]):
            self._load_quran_data()
            
            longest_verse = self.get_verse_by_reference(2, 282)
            
            if longest_verse:
                arabic_normalized = re.sub(r'[\u064B-\u065F\u0670]', '', longest_verse.get('arabic', ''))
                arabic_length = len(arabic_normalized.strip())
                
                return (
                    f"📖 **The Longest Verse in the Holy Quran:**\n\n"
                    f"**{longest_verse['surah_name']} ({longest_verse['surah_translation']}) "
                    f"— {longest_verse['surah_id']}:{longest_verse['verse_id']}**\n\n"
                    f"📝 **Ayat al-Dayn (آيَة ٱلدَّيْن — The Verse of Debt)** is widely recognized in Islamic scholarship as "
                    f"the longest verse in the Quran. It provides detailed guidance on financial transactions, "
                    f"contracts, witnesses, and the importance of documenting debts. This verse reflects Islam's "
                    f"comprehensive approach to social justice and economic ethics.\n\n"
                    f"🔤 **Arabic Text:**\n{longest_verse['arabic']}\n\n"
                    f"**English Translation:**\n_{longest_verse['english']}_\n\n"
                    f"📊 **Statistics:**\n"
                    f"• Approximate character count (without diacritics): **{arabic_length:,}**\n"
                    f"• Appears in: **Juz 3**\n\n"
                    f"📌 _This verse spans nearly a full page in most standard mushafs and covers Islamic principles "
                    f"of contracts, witnesses, and financial integrity in extensive detail._"
                )
            else:
                return "📖 Verse 2:282 (Ayat al-Dayn) is widely recognized in Islamic scholarship as the longest verse. Please verify data availability."

        if any(p in ql for p in ["shortest verse", "shortest ayah", "shortest ayat"]):
            self._load_quran_data()
            
            verses_by_length = []
            for s in self.quran_data:
                for v in s.get("array", []):
                    arabic_text = v.get("ar", "").strip()
                    if not arabic_text:
                        continue
                    arabic_normalized = re.sub(r'[\u064B-\u065F\u0670]', '', arabic_text)
                    verses_by_length.append({
                        "surah_name": s.get("name_en", ""),
                        "surah_translation": s.get("name_translation", ""),
                        "surah_id": s.get("id"),
                        "verse_id": v.get("id"),
                        "english": v.get("en", ""),
                        "arabic": arabic_text,
                        "length": len(arabic_normalized.strip())
                    })
            
            verses_by_length.sort(key=lambda x: x["length"])
            
            if not verses_by_length:
                return "📖 Could not determine the shortest verse."
            
            top_shortest = verses_by_length[:5]
            
            result = "📖 **Scholarly Discussion: The Shortest Verse in the Holy Quran**\n\n"
            result += "📌 **Important Note:** There is no universal scholarly consensus on what constitutes "
            result += "the \"shortest verse.\" The determination depends on the criteria used:\n\n"
            result += "• **Counting individual Arabic letters**\n"
            result += "• **Counting complete words**\n"
            result += "• **Whether to count disconnected letters (al-Ḥurūf al-Muqaṭṭaʿāt) as verses**\n\n"
            
            result += f"**By Character Count — Shortest Verses:**\n\n"
            
            for i, v in enumerate(top_shortest[:5], 1):
                result += f"**{i}.** {v['surah_name']} ({v['surah_translation']}) "
                result += f"— {v['surah_id']}:{v['verse_id']}\n"
                result += f"🔤 {v['arabic']}\n"
                result += f"{v['english']}_\n"
                result += f"📊 Characters: {v['length']}\n\n"
            
            result += "📌 **Scholarly Perspectives:**\n\n"
            result += "• Some scholars consider **Surah Al-Kawthar (108:1)** — \"إِنَّا أَعْطَيْنَاكَ الْكَوْثَرَ\" — "
            result += "the shortest verse by word count (one complete sentence).\n\n"
            result += "• Others note **Surah Ar-Rahman (55:64)** — \"مُدْهَامَّتَانِ\" — as consisting of "
            result += "a single Arabic word.\n\n"
            result += "• The **Muqaṭṭaʿāt letters** (e.g., الم, طه, يس, حم) found at the beginning of 29 surahs "
            result += "are considered by many scholars to be independent verses, which would make them "
            result += "among the shortest segments in the Quran.\n\n"
            result += "📌 **Conclusion:** The definition of \"shortest verse\" varies based on scholarly methodology. "
            result += "The verses listed above are among the briefest by character length, but this classification "
            result += "is one of several valid interpretive approaches."
            
            return result

        if any(p in ql for p in ["total", "whole quran", "entire quran", "quran total", "quran statistics"]):
            total_v = sum(len(s.get("array", [])) for s in self.quran_data)
            total_w = sum(s.get("words", 0) for s in self.quran_data)
            total_l = sum(s.get("letters", 0) for s in self.quran_data)
            
            makki_count = sum(1 for s in self.quran_data if s.get("type_en", "").lower() == "meccan")
            madani_count = sum(1 for s in self.quran_data if s.get("type_en", "").lower() == "medinan")
            
            return (
                f"📊 **The Holy Quran — Overview and Statistics**\n\n"
                f"📖 The Quran (القُرْآن) is the central religious text of Islam and"
                f"the verbatim word of Allah (God) as revealed to Prophet Muhammad ﷺ through the Angel "
                f"Jibreel (Gabriel). Its revelation spanned approximately 23 years, beginning in 610 CE.\n\n"
                f"📊 **Structure:**\n"
                f"• Surahs (Chapters): **114**\n"
                f"  - Makki (Meccan): {makki_count}\n"
                f"  - Madani (Medinan): {madani_count}\n"
                f"• Verses (Ayat): **{total_v:,}**\n"
                f"• Words: **{total_w:,}**\n"
                f"• Letters: **{total_l:,}**\n"
                f"• Juz (Parts): **30**\n"
                f"• Hizb (Half-Juz sections): **60**\n"
                f"• Manzil (Stages for weekly recitation): **7**\n"
                f"• Ruku' (Thematic sections): **540**\n\n"
                f"📜 **Key Reference Points:**\n"
                f"• First revelation: **Surah Al-'Alaq (96:1-5)**\n"
                f"• Last revelation: **Surah Al-Ma'idah (5:3)and 2:281** mong commonly cited views \n"
                f"• Longest surah: **Al-Baqarah (2)** — 286 verses\n"
                f"• Shortest surah: **Al-Kawthar (108)** — 3 verses\n"
                f"• Longest verse: **Ayat al-Dayn (2:282)**\n"
                f"• Bismillah (بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ): Appears **114** times\n"
                f"  - At the beginning of 113 surahs (all except Surah At-Tawbah)\n"
                f"  - Once within **Surah An-Naml (27:30)** as part of Prophet Sulayman's letter\n\n"
                f"📌 **Important Considerations:**\n"
                f"• Verse counts may slightly differ across regional recitations (Qira'at)\n"
                f"• Word and letter counts are based on the Uthmani script and exclude diacritical marks\n"
                f"• Classification of verses as Makki or Madani follows majority scholarly opinion\n\n"
                f"🔍 _For detailed study of specific surahs or verses, ask: \"Tell me about surah [name]\" "
                f"or \"Show me verse [number]:[number]\"_"
            )
        return None

    def _handle_surah_summary_query(self, surah_name: str, user_id: str = "default") -> str:
        summary = self.get_surah_summary(surah_name)
        if not summary:
            return (
                f"📖 I couldn't find Surah '{surah_name}'. "
                "Try the full name (e.g. 'Al-Fatihah', 'Ya-Sin', 'Al-Baqarah') "
                "or say 'surah 1' for Surah Al-Fatihah."
            )

        ctx = self._get_user_context(user_id)
        ctx["last_surah_id"]   = summary["id"]
        ctx["last_surah_name"] = summary["name"]

        alt_names = (
            " | ".join(summary["surah_names"][:4])
            if summary.get("surah_names") else "—"
        )

        resp = (
            f"📖 **{summary['name']} ({summary['translation']})** — {summary['arabic']}\n\n"
            f"📝 **Summary:** {summary['summary']}\n\n"
            f"📌 **Key Topics:** {', '.join(summary['main_topics'][:6])}\n\n"
            f"📊 **Details:**\n"
            f"• Verses: **{summary['verse_count']}** | "
            f"Words: **{summary['words']}** | "
            f"Letters: **{summary['letters']}**\n"
            f"• Revelation: **{summary['revelation_type'].capitalize()}** | "
            f"Juz: **{summary['juz'] or 'N/A'}**\n"
            f"• Also known as: _{alt_names}_\n\n"
            f"📜 **First Verse:**\n"
            f"_{summary['first_verse_arabic']}_\n"
            f"\"{summary['first_verse_english']}\""
        )

        if summary.get("first_verse_urdu"):
            resp += f"\n\n**Urdu:** {summary['first_verse_urdu']}"

        resp += "\n\n🔍 _Ask me for a specific verse — e.g. 'verse 5 of this surah'_"
        return resp

    def _handle_verse_reference_query(self, surah_id: int, verse_id: int, user_id: str = "default") -> str:
        verse = self.get_verse_by_reference(surah_id, verse_id)
        if not verse:
            return (
                f"📖 Verse {surah_id}:{verse_id} not found. "
                "Please verify the reference (surah 1–114, verse number must exist)."
            )

        ctx = self._get_user_context(user_id)
        ctx["last_surah_id"]   = surah_id
        ctx["last_surah_name"] = verse["surah_name"]
        ctx["last_verse_id"]   = verse_id

        resp = (
            f"📖 **{verse['surah_name']} ({verse['surah_translation']}) "
            f"— {surah_id}:{verse_id}**\n\n"
            f"🔤 **Arabic:**\n{verse['arabic']}\n\n"
            f"**English:**\n_{verse['english']}_"
        )

        if verse.get("transliteration"):
            resp += f"\n\n🔊 **Transliteration:**\n_{verse['transliteration']}_"

        if verse.get("urdu"):
            resp += f"\n\n**Urdu:**\n{verse['urdu']}"

        if verse.get("kashmiri"):
            ks = verse["kashmiri"]
            if len(ks) > 400:
                resp += (
                    f"\n\n🏔️ **Kashmiri (Tafsir):**\n{ks[:600]}...\n"
                    f"_📲 Open the full verse in the app for complete Kashmiri Tafsir._"
                )
            else:
                resp += f"\n\n🏔️ **Kashmiri:**\n{ks}"

        similar = self.get_similar_ayahs(surah_id, verse_id, top_n=2, min_score=50)
        if similar:
            resp += "\n\n📎 **Similar Verses:**"
            for sv in similar:
                resp += (
                    f"\n• **{sv['surah_name']} {sv['surah_id']}:{sv['verse_id']}**"
                    f" _(similarity {sv.get('similarity_score', '?')}%)_\n"
                    f"  _{sv['english'][:300]}_"
                )

        return resp

    def _handle_similar_ayahs_query(self, surah_id: int, verse_id: int) -> str:
        similar = self.get_similar_ayahs(surah_id, verse_id, top_n=5, min_score=40)
        if not similar:
            return (
                f"📖 No similar verses found for {surah_id}:{verse_id} "
                "in the similarity index."
            )
        lines = [f"📎 **Verses Similar to {surah_id}:{verse_id}:**\n"]
        for sv in similar:
            lines.append(
                f"**{sv['surah_name']} {sv['surah_id']}:{sv['verse_id']}**"
                f" — _similarity {sv.get('similarity_score')}%, "
                f"coverage {sv.get('similarity_coverage')}%_\n"
                f"🔤 {sv['arabic']}\n"
                f"🇬🇧 _{sv['english'][:250]}_\n"
            )
        return "\n".join(lines)
    
    def _handle_quran_topic_query(self, query: str) -> str:
        result  = self.search_quran_by_topic(query)
        surahs  = result.get("surahs", [])
        verses  = result.get("verses", [])

        if not surahs and not verses:
            return self._fallback_response()

        parts = []

        if surahs:
            parts.append("📖 **Related Surahs:**")
            for s in surahs:
                meta   = s.get("_metadata", {})
                vc     = meta.get("verse_count", len(s.get("array", [])))
                topics = ", ".join(meta.get("main_topics", [])[:3])
                parts.append(
                    f"• **{s.get('name_en')}** ({s.get('name_translation')}) "
                    f"— {vc} verses | _{topics}_"
                )

        if verses:
            parts.append("\n📜 **Key Verses:**")
            for v in verses[:5]:
                parts.append(
                    f"\n**{v['surah_name']} ({v['surah_translation']}) "
                    f"{v['surah_id']}:{v['verse_id']}**"
                )
                
                if v.get("matched_topics"):
                    topic_names = ", ".join(t["name"] for t in v["matched_topics"][:4])
                    parts.append(f"🏷️ **Matched Topics:** {topic_names}")
                
                parts.append(
                    f"{v['arabic']}\n"
                    f"**English:**\n_{v['english'][:300]}_"
                )
                if v.get("urdu"):
                    parts.append(f"**Urdu:**\n{v['urdu'][:200]}")
                if v.get("kashmiri"):
                    ks = v["kashmiri"]
                    parts.append(f"🏔️ **Kashmiri:**\n{ks[:200]}{'...' if len(ks) > 200 else ''}")

        parts.append("\n🤲 _For complete tafsir, open the full surah in the SiratSync app._")
        return "\n".join(parts)
    
    def get_topic_verses_formatted(self, query: str) -> tuple[str, str]:
        """
        Returns (verses_block, raw_context_for_llm) for quran topic queries.
        verses_block   — clean formatted verses to show verbatim to the user
        raw_context    — plain English context to pass to LLM for explanation only
        """
        result  = self.search_quran_by_topic(query)
        verses  = result.get("verses", [])
        surahs  = result.get("surahs", [])

        if not verses and not surahs:
            return "", ""

        # ── Part 1: Verbatim verse block shown to user ──────────────────────
        verse_lines = ["📖 **Related Verses:**\n"]
        for v in verses[:4]:
            ref = f"{v['surah_name']} ({v['surah_translation']}) — {v['surah_id']}:{v['verse_id']}"
            verse_lines.append(f"**{ref}**")
            if v.get("arabic"):
                verse_lines.append(f"{v['arabic']}")
            verse_lines.append(f"**English:** {v['english']}")
            if v.get("urdu"):
                verse_lines.append(f"**Urdu:** {v['urdu']}")
            if v.get("kashmiri"):
                verse_lines.append(f"**Kashmiri:** {v['kashmiri']}")
            verse_lines.append("")  # blank line between verses

        verses_block = "\n".join(verse_lines)

        # ── Part 2: Plain context for LLM explanation ────────────────────────
        ctx_lines = ["Quranic verses on this topic:"]
        for v in verses[:4]:
            ctx_lines.append(
                f"{v['surah_name']} {v['surah_id']}:{v['verse_id']} — {v['english']}"
            )
        raw_context = "\n".join(ctx_lines)

        return verses_block, raw_context

    @staticmethod
    def _fallback_response() -> str:
        return (
            "📖 I couldn't find specific verses on this topic. Try:\n"
            "• A specific surah name: _'tell me about surah yasin'_\n"
            "• A verse reference: _'2:255'_\n"
            "• A clearer topic: _'what does Quran say about patience'_\n"
            "• A Juz: _'surahs in juz 30'_"
        )

    def _update_surah_context(self, surah: dict, user_id: str = "default") -> None:
        ctx = self._get_user_context(user_id)
        ctx["last_surah_id"]   = surah.get("id")
        ctx["last_surah_name"] = surah.get("name_en")
        ctx["last_verse_id"]   = None

    # ═════════════════════════════════════════════════════════════════════════
    # DIRECT ANSWERS
    # ═════════════════════════════════════════════════════════════════════════
    def get_direct_answer(self, query: str) -> Optional[str]:
        ql = query.lower()

        if any(p in ql for p in [
            "who is kaiser", "who made", "who created", "who built",
            "kaiser mohiuddin", "developer of siratsync", "founder",
        ]):
            return (
        "👨‍💻 **Kaiser Mohiuddin** is a Computer Science Engineering student, founder, "
        "and developer of SiratSync — an AI-powered Islamic platform focused on helping "
        "Muslims strengthen their daily Islamic lifestyle through modern technology, "
        "authentic knowledge, and meaningful digital solutions.\n\n"
        "Driven by a passion for faith, innovation, and community impact, he is committed "
        "to building technology that benefits the Ummah.\n\n"
        "📧 Contact: lonekaiser04@gmail.com"
         )

        if any(p in ql for p in [
            "what is siratsync", "siratsync app", "tell me about siratsync",
            "about siratsync",
        ]):
            return (
        "📱 **SiratSync** is a thoughtfully designed AI-powered Islamic lifestyle app built "
        "to help Muslims stay connected to their deen through authentic knowledge, daily "
        "practice, and modern technology — all in one place.\n\n"
        "✨ Key Features:\n"
        "📖 Quran (English, Urdu, Kashmiri Tafsir)\n"
        "🤖 Sirat Assistant (AI Islamic guidance, explanations & learning support)\n"
        "📝 AI Post Summarization for quick, respectful Islamic content understanding\n"
        "🕌 Prayer Times, Adhan & Qibla Finder\n"
        "📚 Hadith (Sahih Bukhari & Sahih Muslim)\n"
        "📿 Duas, Dhikr & Digital Tasbih\n"
        "⭐ Islamic Habit Tracker & Salah Learning\n"
        "🌙 Ramadan Mode & Islamic Calendar\n"
        "👥 Islamic Community & Faith-Based Engagement\n"
        "☪️ Shahadah Guidance and Daily Islamic Essentials\n\n"
        "SiratSync combines faith and innovation to make Islamic learning, reflection, "
        "and daily practice easier, smarter, and more meaningful."
            )

        if any(p in ql for p in ["siratsync features", "app features", "what can it do", "what can you do"]):
            return (
                "✨ **SiratSync Features:**\n"
                "📖 Quran with multiple translations (English / Kashmiri Tafsir / Urdu)\n"
                "🕌 Accurate Prayer Times + Adhan notifications\n"
                "🧭 Qibla Finder (works offline)\n"
                "📚 Sahih Bukhari & Sahih Muslim Hadith\n"
                "📿 Duas & Supplications by situation\n"
                "⭐ Ibadah Habit Tracker with streaks\n"
                "🤲 Digital Tasbih Counter\n"
                "🌙 Ramadan Mode (Suhoor/Iftar + duas)\n"
                "👥 Peaceful Islamic Community\n"
                "🤖 Sirat Assistant (AI Islamic guidance, explanations & learning support)\n"
                 "📝 AI Post Summarization for quick, respectful Islamic content understanding\n"
                "🎯 Learn Salah step-by-step\n"
                "☪️ Shahadat in 14 languages\n"
                "📅 Hijri Islamic Calendar\n"
                "🌓 Beautiful light/dark themes\n"
                "📴 Offline support (Quran, Hadith, Duas, Qibla, Tasbih)"
            )

        if "prayer time" in ql or "salah time" in ql or "namaz time" in ql:
            return (
                "🕌 SiratSync provides accurate prayer times based on your location. "
                "Supports multiple calculation methods (MWL, ISNA, Egypt, Makkah) "
                "and madhhabs. Features include Adhan notifications, early reminders, "
                "and Ramadan special timings."
            )

        if "quran" in ql and any(p in ql for p in ["read", "translation", "open"]):
            return (
            "📖 **The Quran Module in SiratSync** is thoughtfully designed to offer a smooth, "
            "immersive, and spiritually enriching Quran experience.\n\n"
            "✨ Features include:\n"
            "📜 Elegant Arabic script with clear readability\n"
            "🌍 English, Urdu, and Kashmiri translations (including Kashmiri Tafsir)\n"
            "🎨 Customizable font size, spacing, and theme options for personalized reading\n"
            "🔖 Ayah bookmarking for quick access and reflection\n"
            "📖 Mushaf-style layout for a traditional Quran reading experience\n"
            "📱 Full offline access for uninterrupted recitation and study anytime, anywhere\n\n"
            "Built for both learning and daily recitation, the Quran module combines authenticity, "
            "comfort, and accessibility in one powerful experience."
        )

        if any(p in ql for p in ["habit", "streak", "consistent", "track ibadah"]):
            return (
                "⭐ The Habit Tracker helps you build consistency in Salah, Quran "
                "reading, Fasting, and Dhikr. Set daily goals, earn streaks, and view "
                "progress charts. The Prophet ﷺ said: _'The most beloved deeds to Allah "
                "are those done consistently, even if small.'_ (Sahih Bukhari)"
            )

        if any(p in ql for p in ["hadith", "bukhari", "sahih", "sunnah"]):
            return (
                "📚 **The Hadith Module in SiratSync** provides authentic access to essential "
                "Hadith collections, helping users learn and reflect on the teachings of Prophet Muhammad ﷺ.\n\n"
                "✨ Features include:\n"
                "📖 Sahih al-Bukhari & Sahih Muslim collections\n"
                "🗂️ Browse by book, chapter, and category for structured learning\n"
                "🔍 Powerful search for quick Hadith discovery\n"
                "🔖 Bookmark and save favorite Hadith for future reflection\n"
                "📤 Share Hadith easily with others\n"
                "⏰ Daily Hadith reminders for consistent spiritual growth\n"
                "📚 Continuous expansion with more authentic collections planned\n\n"
                "Designed for accessibility and authenticity, SiratSync makes studying Hadith "
                "simple, organized, and meaningful."
            )

        if any(p in ql for p in ["learn salah", "how to pray", "namaz guide", "prayer guide"]):
            return (
                "🎯 SiratSync's Learn Salah module provides a step-by-step guide "
                "covering actions, words, and meanings — perfect for beginners or "
                "anyone wanting to improve their prayer."
            )

        if ("community" in ql and "siratsync" in ql) or ("community" in ql and "app" in ql):
            return (
                "👥 **SiratSync Community** is a peaceful, faith-centered Islamic social space "
                "designed to help Muslims connect, share, and grow together while maintaining "
                "adab, authenticity, and safety.\n\n"
                "✨ Features include:\n"
                "📝 Share Islamic reminders, duas, reflections, and beneficial content\n"
                "👤 Follow like-minded users and build a meaningful Islamic network\n"
                "📰 Personalized Islamic feed curated for inspiration and learning\n"
                "🤖 AI-powered post summarization for quick, respectful understanding of content\n"
                "🛡️ Strong moderation focused on cleanliness, respect, and Islamic values\n"
                "🌍 A positive digital environment that encourages beneficial engagement\n\n"
                "Built to combine community, knowledge, and Islamic etiquette, SiratSync Community "
                "offers a safer and more purposeful social experience for the Ummah."
            )

        if "ramadan" in ql and any(p in ql for p in ["mode", "app", "feature", "siratsync"]):
            return (
                "🌙 Ramadan Mode includes Suhoor & Iftar timings, Ramadan duas, "
                "fasting reminders, and special Qiyam notifications for a blessed month."
            )

        if "offline" in ql:
            return (
                "📴 **SiratSync Offline Access** ensures your essential Islamic resources remain "
                "available anytime, anywhere — even without an internet connection.\n\n"
                "✨ Available Offline Features:\n"
                "📖 Quran with translations and Tafsir support\n"
                "📚 Sahih al-Bukhari & Sahih Muslim\n"
                "📿 Duas, Dhikr & Aurad-e-Fatiha\n"
                "🧭 Qibla Finder\n"
                "📿 Digital Tasbih Counter\n"
                "🕌 Cached Prayer Times for continued daily guidance\n\n"
                "⬇️ Simply download once, and access your core Islamic tools whenever needed — "
                "whether traveling, in remote areas, or conserving data.\n\n"
                "SiratSync is built for reliability, ensuring your connection to deen remains "
                "uninterrupted wherever you are."
            )

        if "qibla" in ql or "kibla" in ql:
            return (
                "🧭 The Qibla Finder provides high-accuracy compass direction to Mecca. "
                "Calibrate by moving your phone in a figure-8 motion, then follow the "
                "arrow. Works offline after calibration."
            )

        if any(p in ql for p in [
            "how many surahs", "how many chapters", "total surahs",
            "surahs in quran", "chapters in quran",
        ]):
            return (
                "📖 **The Holy Quran** is the final divine revelation revealed to Prophet Muhammad ﷺ "
                "over approximately 23 years as guidance for humanity.\n\n"
                "✨ Quran at a Glance:\n"
                "📚 114 Surahs (chapters)\n"
                "📝 6,236 Ayat (verses)\n"
                "📖 30 Juz (parts)\n"
                "🌍 Revealed gradually for spiritual, moral, and practical guidance\n\n"
                "The Quran covers faith, worship, character, law, history, and wisdom — serving "
                "as a complete source of guidance for Muslims in every aspect of life."
            )

        return None

    # ═════════════════════════════════════════════════════════════════════════
    # KNOWLEDGE-BASE KEYWORD FALLBACK
    # ═════════════════════════════════════════════════════════════════════════
    def _keyword_fallback(self, ql: str, top_k: int = 4) -> str:
        PRIORITY_MAP = {
            "salah":        ["salah", "prayer", "namaz", "fajr", "dhuhr", "asr", "maghrib", "isha", "adhan"],
            "quran":        ["quran", "recitation", "tilawat", "surah", "ayat", "translation"],
            "dua":          ["dua", "supplication", "adhkar", "dhikr"],
            "hadith":       ["hadith", "bukhari", "muslim", "sunnah", "sahih"],
            "productivity": ["habit", "consistent", "streak", "tracking", "istiqamah"],
            "developer":    ["kaiser", "developer", "who made", "founder"],
            "siratsync":    ["siratsync", "app", "features"],
            "qibla":        ["qibla", "kibla", "mecca", "kaaba"],
            "tasbih":       ["tasbih", "counter", "subhanallah", "alhamdulillah"],
            "ramadan":      ["ramadan", "suhoor", "iftar", "fasting"],
            "community":    ["community", "social", "feed"],
            "offline":      ["offline", "no internet"],
        }

        priority_cat = next(
            (cat for cat, kws in PRIORITY_MAP.items() if any(kw in ql for kw in kws)),
            None,
        )

        query_words = set(ql.split())
        scored: list[tuple[float, str]] = []

        for item in self.search_index:
            score = float(len(query_words & item["keywords"]))
            if priority_cat and priority_cat in item["category"].lower():
                score += 15
            if isinstance(item["item"], dict):
                for field in ("topic", "situation", "intent_name"):
                    val = item["item"].get(field, "").lower()
                    if val and val in ql:
                        score += 8
            if score <= 0:
                continue

            d   = item["item"]
            pfx = {
                "developer": "👨‍💻", "duas": "📿", "salah": "🕌",
                "productivity": "⚡", "app_features": "📱", "ramadan": "🌙",
                "faqs": "❓", "responses": "💬", "app_info": "ℹ️",
            }.get(item["category"], "📌")

            text = d.get("answer") or d.get("description") or d.get("content", str(d))
            if d.get("reference"):
                text += f"\n📚 {d['reference']}"
            scored.append((score, f"{pfx} {text}"))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return (
                "📖 **I’m here to help with Islamic guidance and everything SiratSync offers.**\n\n"
                "✨ You can ask me about:\n"
                "🕌 Salah, Prayer Times & Adhan\n"
                "📖 Quran, Translations & Tafsir\n"
                "📿 Duas, Dhikr & Daily Islamic Practices\n"
                "📚 Hadith Collections & Sunnah\n"
                "🤖 Sirat Assistant & AI Islamic Learning\n"
                "📝 AI Post Summarization\n"
                "⭐ Islamic Habit Tracking\n"
                "🧭 Qibla Direction\n"
                "🌙 Ramadan Mode & Islamic Calendar\n"
                "👥 SiratSync Community\n"
                "🎯 Learn Salah Step-by-Step\n"
                "📿 Digital Tasbih & More\n\n"
                "Ask anything related to Islam, daily worship, or SiratSync features — and I’ll do my best to assist you clearly and respectfully."
            )

        result = "\n\n".join(text for _, text in scored[:top_k])
        return result[:2500] + "..." if len(result) > 2500 else result

    # ═════════════════════════════════════════════════════════════════════════
    # LEGACY / COMPAT
    # ═════════════════════════════════════════════════════════════════════════
    def get_category_summary(self, category: str) -> str:
        if category in self.knowledge:
            items = self.knowledge[category]
            count = len(items) if isinstance(items, list) else len(items)
            return f"📚 {category.upper()}: {count} items"
        return f"Category '{category}' not found"

# ── Singleton ────────────────────────────────────────────────────────────────
rag_service = RAGKnowledge()