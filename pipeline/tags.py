"""Tag clean-up. Source tags are free text: this keeps what describes the content."""
import re

MAX_TAGS = 12
DROP = frozenset("""
music radio fm am misc internet webradio web online live stream estación entretenimiento
música méxico mexico norteamérica latinoamérica américa español local regional
aac aacp mp3 ogg opus flac hd hifi kbps moi merino variety various other station emisora rádio musica musik
""".split()) | {"moi merino", "internet radio", "local radio", "regional radio", "música variada",
                "programas en vivo", "música en español", "música en español e inglés"}
ALIASES = {
    "hiphop": "hip-hop", "hip hop": "hip-hop", "rap": "hip-hop",
    "electro": "electronic", "electronica": "electronic", "edm": "electronic",
    "classic": "classical", "clásica": "classical", "classique": "classical",
    "noticias": "news", "information": "news", "actualités": "news", "news talk": "news",
    "música pop": "pop", "pop music": "pop", "pop rock": "pop",
    "christian music": "christian", "religious": "religion", "religion": "religion",
    "top 40": "hits", "top40": "hits", "classic hits": "oldies",
    "talk radio": "talk", "sport": "sports", "public radio": "public",
    "community radio": "community",
}


def clean_tags(raw_lists):
    """Merge several comma-separated lists, most frequent first, then by name."""
    counts = {}
    for raw in raw_lists:
        seen = set()
        for tag in (raw or "").split(","):
            tag = re.sub(r"\s+", " ", tag).strip().lower().lstrip("#")
            tag = ALIASES.get(tag, tag)
            if 2 <= len(tag) <= 40 and tag not in DROP and tag not in seen:
                seen.add(tag)
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts, key=lambda t: (-counts[t], t))[:MAX_TAGS]
