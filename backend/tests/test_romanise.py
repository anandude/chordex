"""Everyday romanisation of Indic lyrics (pipeline/romanise.py)."""

import pytest

pytest.importorskip("aksharamukha")

from pipeline.romanise import romanise, romanise_segments, script_of  # noqa: E402


@pytest.mark.parametrize("native, roman", [
    # Hindi — schwa deletion, nasals, Hinglish spellings
    ("तुम ही हो, अब तुम ही हो, ज़िंदगी अब तुम ही हो",
     "tum hi ho, ab tum hi ho, zindagi ab tum hi ho"),
    ("तू ही ये मुझ को बता दे चाहूँ मैं या ना", "tu hi ye mujh ko bata de chahun main ya na"),
    ("दिल की धड़कन समझता है कहना", "dil ki dhadkan samajhta hai kahna"),
    ("मुझको हमेशा आपके दिलों में रहेंगे", "mujhko hamesha apke dilon mein rahenge"),
    ("यह दिल वह बातें नहीं हैं।", "yeh dil woh batein nahin hain."),
    ("हम तेरे बिन अब रह नहीं सकते", "hum tere bin ab rah nahin sakte"),
    ("लड़की पढ़ना संभाल ज्ञान कृष्ण", "ladki padhna sambhal gyan krishna"),
    ("चलते चलते सपने", "chalte chalte sapne"),
    ("रंग पतंग ट्रेनिंग अच्छा", "rang patang trening achha"),
    # Malayalam — Kerala spellings
    ("മഴ ഞാൻ അറിഞ്ഞിരുന്നില്ല നിന്റെ കണ്ണുകളിൽ",
     "mazha njaan arinjirunnilla ninte kannukalil"),
    ("എന്റെ ഖൽബിലെ വെണ്ണിലാവു നീ", "ente khalbile vennilaavu nee"),
    ("കാറ്റ് ചിരിക്കും, ഹൃദയം, സ്നേഹം", "kaattu chirikkum, hrudayam, sneham"),
    ("ഒരു പുഷ്പം മാത്രമെൻ പൂങ്കുലയിൽ", "oru pushpam maathramen poonkulayil"),
    ("എൻ്റെ ഉള്ളിൽ നെഞ്ചിരി നേർത്തു പടരും വരെ",
     "ente ullil nenchiri nerthu padarum vare"),
    ("നിൻ്റെ കണ്ണു നീരെന്നുള്ളിലുതിരും", "ninte kannu neerennulliluthirum"),
    ("ഞാൻ കണ്ടു ഒത്തിരി", "njaan kandu otthiri"),
    # Tamil — generic colloquial path
    ("உன்னை நினைத்து", "unnai ninaiththu"),
])
def test_everyday_spelling(native, roman):
    assert romanise(native) == roman


def test_latin_untouched():
    assert romanise("Wise men say") == "Wise men say"
    assert script_of("Wise men say") is None
    assert script_of("ok मैं") == "Devanagari"


@pytest.mark.parametrize("segs, expected", [
    (["मु", "झ", "को"], ["mu", "jh", "ko"]),
    (["ज़िं", "द", "गी"], ["zin", "da", "gi"]),
    (["अ", "रि"], ["a", "ri"]),
    (["അ", "റി", "ഞ്ഞി", "രു", "ന്നി", "ല്ല"], ["a", "ri", "nji", "ru", "nni", "lla"]),
])
def test_segments_follow_syllables(segs, expected):
    assert romanise_segments(segs) == expected


@pytest.mark.parametrize("segs", [
    ["सम", "झ", "ता"], ["കാ", "റ്റ്"], ["ध", "ड़", "क", "न"], ["x"],
])
def test_segments_always_rejoin_to_the_word(segs):
    out = romanise_segments(segs)
    assert len(out) == len(segs)
    assert "".join(out) == romanise("".join(segs))
