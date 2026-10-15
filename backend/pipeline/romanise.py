"""
pipeline/romanise.py
--------------------
Indic lyrics → the everyday Roman spelling people actually type
("tum hi ho, ab tum hi ho", "mazha njan arinjirunnilla"), not a scholarly
scheme ("tuma hI ho", "maḻa ñān").

Approach: aksharamukha (with its Hindi schwa-deletion pass) converts native
script to IAST, which is unambiguous — one letter per sound (ñ = ഞ, ṟ = റ,
ṃ = anusvara). Small per-script tables then map IAST to colloquial spelling:

* Devanagari (Hindi): drop vowel length, c→ch, ś/ṣ→sh, jñ→gy, nasal ṃ → n
  (m before p/b/m), word-final "eṃ" → "ein" (में → mein, हैं → hain).
* Malayalam (Manglish): ഞ → nj, ന്റ → nt, റ്റ → tt, ത → th, ട → d between
  vowels, ഴ → zh, ṛ → ru, final ് → u (കാറ്റ് → kaattu), anusvara → m, long
  vowels doubled (njaan, nee, poove).
* Other Indic scripts: aksharamukha's RomanColloquial as-is.

Hinglish/Manglish spelling is not standardised ("zindagi"/"zindgi",
"njan"/"njaan"); the goal is consistent and readable, following the most
common convention per language: Hinglish writes long vowels single (tu hi),
Manglish doubles them (njaan, nee).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

logger = logging.getLogger(__name__)

# Unicode block → aksharamukha script name.
_SCRIPTS = [
    (0x0900, 0x097F, "Devanagari"),
    (0x0980, 0x09FF, "Bengali"),
    (0x0A00, 0x0A7F, "Gurmukhi"),
    (0x0A80, 0x0AFF, "Gujarati"),
    (0x0B00, 0x0B7F, "Oriya"),
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0C00, 0x0C7F, "Telugu"),
    (0x0C80, 0x0CFF, "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam"),
]


def script_of(text: str) -> str | None:
    """aksharamukha name of the first Indic script in ``text`` (None = Latin etc.)."""
    for ch in text:
        cp = ord(ch)
        for lo, hi, name in _SCRIPTS:
            if lo <= cp <= hi:
                return name
    return None


def _strip_marks(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def _common(s: str) -> str:
    """IAST letters shared by Hindi and Malayalam spelling."""
    s = s.replace("cch", "\x02")         # अच्छा → achha (not achchha)
    s = s.replace("ch", "\x00")          # छ (aspirated) before bare c
    s = s.replace("c", "ch").replace("\x00", "chh").replace("\x02", "chh")
    s = s.replace("kṣ", "ksh").replace("ś", "sh").replace("ṣ", "sh")
    s = s.replace("ṅ", "n").replace("ṇ", "n")
    for a, b in (("ā", "a"), ("ī", "i"), ("ū", "u"), ("ē", "e"), ("ō", "o"),
                 ("ĕ", "e"), ("ŏ", "o"), ("ṭ", "t"), ("ḍ", "d"), ("ḥ", "h")):
        s = s.replace(a, b)
    return s


_LABIAL = "pbm"

# ── Hindi schwa deletion (Ohala's rule) on IAST ───────────────────────────
# A written consonant carries an inherent "a" that Hindi often drops:
# तुम → tum, समझता → samajhta, ज़िंदगी → zindagi, धड़कन → dhadkan.
# Rule: drop the word-final schwa (unless the word has one vowel or ends in a
# conjunct: कृष्ण → krishna), then scan right→left dropping a schwa in the
# context V C _ C V. (aksharamukha's own RemoveSchwaHindi drops the wrong one
# in samajhta / zindagi.)
_TOK = re.compile(
    r"(r\u0324h|r\u0324|kh|gh|ch|jh|ṭh|ḍh|th|dh|ph|bh|[kgṅcjñṭḍṇtdnpbmyrlvśṣshqzfxġṃ])"
    r"|(ai|au|ā|ī|ū|ṛ|a|i|u|e|o)(m\u0310)?"
    r"|(.)",
    re.DOTALL,
)


def _delete_schwa(word: str) -> str:
    toks: list[tuple[str, str]] = []  # (kind, text): C consonant, V vowel, O other
    for m in _TOK.finditer(word):
        if m.group(1):
            toks.append(("C", m.group(1)))
        elif m.group(2):
            toks.append(("V", m.group(2) + (m.group(3) or "")))
        else:
            toks.append(("O", m.group(4)))
    kinds = [k for k, _ in toks]
    if "O" in kinds or kinds.count("V") < 2:
        return word
    alive = [True] * len(toks)

    def is_schwa(i: int) -> bool:
        # inherent a = an "a" right after a consonant (word-initial अ is kept)
        return toks[i] == ("V", "a") and i > 0 and kinds[i - 1] == "C"

    def prev_live(i: int) -> int:
        j = i - 1
        while j >= 0 and not alive[j]:
            j -= 1
        return j

    def next_live(i: int) -> int:
        j = i + 1
        while j < len(toks) and not alive[j]:
            j += 1
        return j

    last = len(toks) - 1
    # a true conjunct keeps it (कृष्ण → krishna); anusvara + consonant does
    # not (रंग, ट्रेनिंग → rang, trening)
    conjunct = last >= 2 and kinds[last - 2] == "C" and toks[last - 2][1] != "ṃ"
    if is_schwa(last) and not conjunct:
        alive[last] = False
    for i in range(last - 1, 0, -1):
        if not is_schwa(i):
            continue
        c1 = prev_live(i)
        v1 = prev_live(c1)
        c2 = next_live(i)
        v2 = next_live(c2) if c2 < len(toks) else len(toks)
        if (v1 >= 0 and kinds[v1] == "V" and kinds[c1] == "C"
                and c2 < len(toks) and kinds[c2] == "C"
                and v2 < len(toks) and kinds[v2] == "V"):
            alive[i] = False
    return "".join(t for (_, t), a in zip(toks, alive) if a)


def _schwa_text(iast: str) -> str:
    return re.sub(r"[^\W\d_]+(?:[\u0300-\u036f][^\W\d_]*)*",
                  lambda m: _delete_schwa(m.group(0)), iast)


def _hindi(iast: str) -> str:
    s = _schwa_text(unicodedata.normalize("NFC", iast))
    s = s.replace("jñ", "gy")                       # ज्ञान → gyan
    s = s.replace("ṛ", "ri")                        # कृष्ण → krishna
    s = s.replace("r̤h", "dh").replace("r̤", "d")     # पढ़ना, धड़कन → padhna, dhadkan
    s = s.replace("m̐", "ṃ")                         # chandrabindu ≈ anusvara
    s = re.sub(r"eṃ\b", "ein", s)                   # में, बातें → mein, baatein
    s = re.sub(r"ṃ(?=[" + _LABIAL + "])", "m", s)   # संभाल → sambhal
    s = s.replace("ṃ", "n")                         # मैं, दिलों → main, dilon
    s = s.replace("ñ", "n")
    s = _common(s)
    return _strip_marks(s)


_ML_V = "aeiouāīūēōĕŏ"


def _malayalam(iast: str) -> str:
    s = unicodedata.normalize("NFC", iast)
    # ത is "th" in Manglish (athu, ninte stays nt via ന്റ below); ഥ is th too
    s = s.replace("th", "\x01").replace("t", "th").replace("\x01", "th")
    s = s.replace("thth", "tth")                    # ഒത്തിരി → otthiri
    s = re.sub(f"(?<=[^{_ML_V}])tth", "th", s)      # നേർത്തു → nerthu
    s = re.sub(f"(?<=[{_ML_V}])ṭ(?=[{_ML_V}])", "d", s)  # പടരും → padarum
    s = s.replace("ṇṭ", "nd")                       # കണ്ടു → kandu
    s = s.replace("ñc", "nc").replace("ñj", "nj")   # നെഞ്ച്, ഞ്ജ
    s = s.replace("ññ", "nj").replace("ñ", "nj")   # ഞാൻ, അറിഞ്ഞ് → njaan, arinj
    s = s.replace("nṟ", "nt").replace("ṟṟ", "tt")  # നിന്റെ → ninte, കാറ്റ് → kaattu
    s = s.replace("ṟ", "r").replace("ḻ", "zh")      # മഴ → mazha
    s = s.replace("ṛ", "ru")                        # ഹൃദയം → hrudayam
    s = s.replace("ṅk", "nk").replace("ṅṅ", "ng")   # പൂങ്കുല, ങ്ങ
    s = s.replace("ṃ", "m").replace("l̤", "l")       # anusvara is "m"; ള → l
    # Manglish doubles long vowels: njaan, nee, poove (ē/ō stay single)
    s = s.replace("ā", "aa").replace("ī", "ee").replace("ū", "oo")
    s = _common(s)
    return _strip_marks(s)


# Pronunciation-driven spellings the rules can't derive.
_HINDI_WORDS = {"यह": "yeh", "वह": "woh", "वो": "woh", "हम": "hum"}


def _prep_malayalam(text: str) -> str:
    # word-final virama is the half-u (samvruthokaram): കാറ്റ് → kaattu
    return re.sub("്(?=$|[^ഀ-ൿ])", "ു", text)


@lru_cache(maxsize=20000)
def romanise(text: str) -> str:
    """Colloquial Roman spelling of ``text``; Latin text comes back unchanged.

    Raises ImportError when aksharamukha is missing (callers fall back)."""
    script = script_of(text)
    if script is None:
        return text
    from aksharamukha import transliterate as T

    if script == "Devanagari":
        # Hindi-specific spellings for whole words, rules for the rest
        parts = re.split(r"(\s+)", text)
        out = []
        for p in parts:
            core = p.strip(".,!?;:'\"()-…।")
            if core in _HINDI_WORDS:
                out.append(p.replace(core, _HINDI_WORDS[core]))
            else:
                out.append(p)
        text = "".join(out)
        iast = T.process("Devanagari", "IAST", text)
        roman = _hindi(iast)
    elif script == "Malayalam":
        roman = _malayalam(T.process("Malayalam", "IAST", _prep_malayalam(text)))
    else:
        roman = _strip_marks(T.process(script, "RomanColloquial", text))
    return roman.replace("।", ".").replace("॥", ".")


def _ends_bare_consonant(seg: str) -> bool:
    seg = seg.rstrip("\u093C")  # nukta: ज़ is still a bare consonant
    if not seg:
        return False
    cp = ord(seg[-1])
    return 0x0915 <= cp <= 0x0939 or 0x0958 <= cp <= 0x095F or 0x0D15 <= cp <= 0x0D39


def romanise_segments(segs: list[str]) -> list[str]:
    """Split a word's romanisation across its syllable segments.

    Each segment boundary is located by romanising the native prefix up to it
    — exact whenever the prefix spells the same way inside the word
    (मुझ|को → mujh|ko). Where context changes the spelling (schwa deletion,
    final ് → u), the boundary falls back to a proportional split.
    """
    full = romanise("".join(segs))
    if len(segs) <= 1:
        return [full]
    total = sum(len(s) for s in segs) or 1
    cuts, acc, prev = [], 0, 0
    for s in segs[:-1]:
        acc += len(s)
        pre = romanise("".join(segs)[:acc])
        if full.startswith(pre) and prev <= len(pre) <= len(full):
            cut = len(pre)
            # a segment ending on a bare consonant owns its inherent vowel even
            # when the prefix alone drops it: ज़िं|द|गी → zin|da|gi, not zin|d|agi
            if _ends_bare_consonant(s) and full[cut:cut + 1] == "a":
                cut += 1
        else:
            cut = max(prev, min(len(full), round(acc / total * len(full))))
        cuts.append(cut)
        prev = cut
    bounds = [0, *cuts, len(full)]
    return [full[a:b] for a, b in zip(bounds, bounds[1:])]
