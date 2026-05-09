# generate_rich_metadata.py
import json
import os
import re
from collections import Counter

def build_rich_quran_metadata():
    """
    Automatically generate rich metadata for all 114 surahs
    with proper keywords, topics, and queries
    """
    
    # Find the file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Look for quran_indexed.json
    file_path = None
    search_paths = [
        os.path.join(script_dir, 'quran_indexed.json'),
        os.path.join(script_dir, '..', 'quran_indexed.json'),
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            file_path = path
            break
    
    if not file_path:
        # Search recursively
        for root, dirs, files in os.walk(r"C:\Users\HP\streakly"):
            if "quran_indexed.json" in files:
                file_path = os.path.join(root, "quran_indexed.json")
                break
    
    if not file_path:
        print("❌ quran_indexed.json not found!")
        print("Enter full path: ", end="")
        file_path = input().strip().strip('"')
    
    print(f"📂 Using file: {file_path}")
    
    # Load data
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    quran = data.get('quran', [])
    print(f"📖 Found {len(quran)} surahs")
    
    # Common English stop words
    stop_words = {
        'the', 'is', 'in', 'of', 'and', 'to', 'a', 'for', 'that', 'he', 'she',
        'it', 'they', 'we', 'i', 'you', 'will', 'shall', 'has', 'have', 'been',
        'are', 'was', 'were', 'be', 'being', 'do', 'does', 'did', 'not', 'no',
        'nor', 'but', 'or', 'if', 'then', 'than', 'so', 'as', 'at', 'by', 'from',
        'with', 'his', 'her', 'its', 'their', 'our', 'my', 'your', 'all', 'who',
        'whom', 'which', 'what', 'where', 'when', 'why', 'how', 'this', 'that',
        'these', 'those', 'say', 'said', 'upon', 'may', 'can', 'would', 'could',
        'should', 'there', 'them', 'into', 'also', 'one', 'two', 'three', 'verily',
        'indeed', 'among', 'before', 'after', 'day', 'lord', 'people', 'earth',
        'heavens', 'know', 'truth', 'believe', 'those', 'surely', 'anything'
    }
    
    # Topic patterns
    topic_patterns = {
        'Seeking Refuge & Protection': ['refuge', 'protection', 'protect', 'seek refuge', 'guard'],
        'Creation & Universe': ['create', 'creation', 'heavens', 'earth', 'stars', 'sun', 'moon', 'mountains'],
        'Faith & Belief': ['believe', 'faith', 'believers', 'righteous', 'iman', 'trust'],
        'Prayer & Worship': ['prayer', 'pray', 'worship', 'salah', 'prostrate', 'bow'],
        'Divine Oneness (Tawheed)': ['one god', 'only god', 'no god', 'alone', 'worship him', 'associate'],
        'Guidance & Misguidance': ['guide', 'guidance', 'straight path', 'misguided', 'astray'],
        'Day of Judgment': ['judgment', 'day of judgment', 'resurrection', 'reckoning', 'hereafter'],
        'Paradise & Hell': ['paradise', 'garden', 'jannah', 'hell', 'fire', 'punishment'],
        'Mercy & Forgiveness': ['mercy', 'forgive', 'compassion', 'merciful', 'repentance'],
        'Prophets & Messengers': ['prophet', 'messenger', 'moses', 'abraham', 'noah', 'jesus', 'muhammad'],
        'Moral Laws & Ethics': ['command', 'forbid', 'lawful', 'unlawful', 'righteous', 'evil'],
        'Hypocrites & Disbelievers': ['hypocrite', 'disbelieve', 'reject', 'deny', 'arrogant'],
        'Patience & Trials': ['patient', 'patience', 'trial', 'test', 'hardship', 'affliction'],
        'Gratitude & Blessings': ['grateful', 'gratitude', 'blessing', 'provision', 'sustenance'],
        'Knowledge & Wisdom': ['knowledge', 'wisdom', 'reflect', 'understand', 'signs'],
    }
    
    # Process each surah
    for idx, surah in enumerate(quran):
        print(f"Processing {idx+1}/114 - Surah {surah.get('name_en', 'Unknown')}...", end=" ")
        
        if '_metadata' not in surah:
            surah['_metadata'] = {}
        
        meta = surah['_metadata']
        verses = surah.get('array', [])
        
        if not verses:
            print("❌ No verses")
            continue
        
        # Combine all verse text
        all_en = ' '.join([v.get('en', '') for v in verses if v.get('en')]).lower()
        all_ar = ' '.join([v.get('ar', '') for v in verses if v.get('ar')])
        
        # === 1. EXTRACT MEANINGFUL KEYWORDS ===
        words = re.findall(r'\b[a-z]+\b', all_en)
        filtered = [w for w in words if w not in stop_words and len(w) > 2]
        word_freq = Counter(filtered)
        # Take top 25 meaningful keywords
        auto_keywords = [word for word, count in word_freq.most_common(30) if count >= 2][:25]
        
        # Also add multi-word phrases (bigrams)
        bigrams = []
        for i in range(len(words)-1):
            if words[i] not in stop_words and words[i+1] not in stop_words:
                bigram = f"{words[i]} {words[i+1]}"
                if len(bigram) > 5:
                    bigrams.append(bigram)
        bigram_freq = Counter(bigrams)
        common_phrases = [phrase for phrase, count in bigram_freq.most_common(10) if count >= 2]
        
        # Combine keywords
        meta['keywords_en'] = auto_keywords + common_phrases
        
        # === 2. DETECT MAIN TOPICS ===
        detected_topics = []
        for topic, indicators in topic_patterns.items():
            if any(ind in all_en for ind in indicators):
                detected_topics.append(topic)
        
        if not detected_topics:
            detected_topics = ["General Guidance"]
        
        meta['main_topics'] = detected_topics[:7]  # Max 7 topics
        
        # === 3. GENERATE COMMON QUERIES ===
        name_en = surah.get('name_en', '').lower()
        name_trans = surah.get('name_translation', '').lower()
        
        queries = [
            f"what is surah {name_en}",
            f"tell me about surah {name_en}",
            f"meaning of surah {name_en}",
            f"benefits of surah {name_en}",
            f"surah {name_en} explanation",
            f"read surah {name_en}",
            f"surah {name_en} tafsir",
            f"show me surah {name_en}",
            f"surah number {surah.get('id')}",
        ]
        
        # Add topic-based queries
        for topic in detected_topics[:3]:
            queries.append(f"surah about {topic.lower()}")
        
        # Add translation name if different
        if name_trans and name_trans != name_en:
            queries.append(f"what is surah {name_trans}")
            queries.append(f"meaning of surah {name_trans}")
        
        # Add common question patterns
        if 'protection' in all_en:
            queries.append("surah for protection")
        if 'mercy' in all_en:
            queries.append("surah about mercy")
        if 'creation' in all_en:
            queries.append("surah about creation")
        
        meta['common_queries'] = list(set(queries))[:20]
        
        # === 4. GENERATE RICH SUMMARY ===
        surah_id = surah.get('id', 0)
        verse_count = len(verses)
        revelation = meta.get('revelation_type', 'unknown').capitalize()
        juz = meta.get('juz', '')
        topics_str = ', '.join(detected_topics[:4])
        
        # Generate a meaningful summary
        first_verse_en = verses[0].get('en', '') if verses else ''
        last_verse_en = verses[-1].get('en', '') if verses else ''
        
        summary = f"Surah {surah['name_en']} ({surah.get('name_translation', '')}) is the {surah_id}{'th' if surah_id > 3 else ['st','nd','rd'][surah_id-1]} surah of the Quran. "
        summary += f"Revealed in {revelation}, it contains {verse_count} verses in Juz {juz}. "
        summary += f"Main themes include: {topics_str}. "
        summary += f"It begins with: \"{first_verse_en[:100]}\" and concludes with: \"{last_verse_en[:100]}\"."
        
        meta['summary'] = summary
        
        # === 5. PRESERVE EXISTING GOOD DATA ===
        meta['searchable_text_en'] = all_en
        meta['verse_count'] = verse_count
        
        print("✅")
    
    # Save enhanced file
    output_path = file_path.replace('.json', '_rich.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✅ Successfully generated rich metadata for {len(quran)} surahs!")
    print(f"📁 Saved to: {output_path}")
    print(f"📊 File size: {os.path.getsize(output_path) / (1024*1024):.2f} MB")
    
    # Show sample
    print(f"\n📋 Sample - Surah An-Nas (114):")
    for surah in quran:
        if surah.get('id') == 114:
            meta = surah['_metadata']
            print(f"   Keywords: {meta['keywords_en'][:5]}")
            print(f"   Topics: {meta['main_topics']}")
            print(f"   Sample queries: {meta['common_queries'][:3]}")
            print(f"   Summary: {meta['summary'][:200]}...")
            break
    
    print(f"\n💡 Next steps:")
    print(f"   1. Review the generated file")
    print(f"   2. Update rag_knowledge.py to use 'quran_indexed_rich.json'")
    print(f"   3. Test with some queries")

if __name__ == "__main__":
    build_rich_quran_metadata()