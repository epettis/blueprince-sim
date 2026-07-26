"""resolve_glyphs: mechanical glyph decode for mojibake effect text."""

import sys
from pathlib import Path

import pytest

# tools/ is not a proper package; insert the repo root so the import works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.ingest_sheet import (  # noqa: E402
    GLYPH_BARE,
    GLYPH_COINS,
    GLYPH_DICE,
    GLYPH_STEPS,
    resolve_glyphs,
)


def test_tailed_dice_decoded_mechanically():
    """ð² decodes to dice without consuming an ambiguous entry; the
    tailed form is unambiguous so no map entry is needed."""
    result = resolve_glyphs(f"+2{GLYPH_DICE}", ambiguous=[], room_id="test")
    assert result == [{"icon": "dice", "confidence": "datamined"}]


def test_tailed_coins_decoded_mechanically():
    """ð° decodes to coins without consuming an ambiguous entry."""
    result = resolve_glyphs(f"+4{GLYPH_COINS}", ambiguous=[], room_id="test")
    assert result == [{"icon": "coins", "confidence": "datamined"}]


def test_tailed_steps_decoded_mechanically():
    """ð£ decodes to steps without consuming an ambiguous entry."""
    result = resolve_glyphs(f"+10{GLYPH_STEPS}", ambiguous=[], room_id="test")
    assert result == [{"icon": "steps", "confidence": "datamined"}]


def test_bare_glyph_consumes_ambiguous_in_order():
    """Bare ð consumes one entry per occurrence from the ambiguous list in
    the order they appear — the first bare glyph gets the first ambiguous entry."""
    text = f"Gain {GLYPH_BARE} and {GLYPH_BARE}"
    result = resolve_glyphs(text, [("key", "datamined"), ("gem", "datamined")], room_id="test")
    assert result == [
        {"icon": "key", "confidence": "datamined"},
        {"icon": "gem", "confidence": "datamined"},
    ]


def test_mixed_text_decoded_left_to_right():
    """Mixed text (bare then tailed) decodes in left-to-right order, with tailed
    forms consuming no ambiguous slot — critical for storeroom-style texts."""
    # "+1ð, 1ð, 1ð°"  -> key (bare), gem (bare), coins (tailed)
    text = f"+1{GLYPH_BARE}, 1{GLYPH_BARE}, 1{GLYPH_COINS}"
    result = resolve_glyphs(
        text,
        [("key", "datamined"), ("gem", "datamined")],
        room_id="test",
    )
    assert result == [
        {"icon": "key", "confidence": "datamined"},
        {"icon": "gem", "confidence": "datamined"},
        {"icon": "coins", "confidence": "datamined"},
    ]


def test_bare_then_tailed_then_bare_order():
    """Interleaved bare and tailed glyphs decode in the correct positional order;
    tailed forms never consume an ambiguous entry from between two bare glyphs."""
    # Simulate: key (bare), steps (tailed), gem (bare)
    text = f"1{GLYPH_BARE} per room, {GLYPH_STEPS} cost, {GLYPH_BARE} reward"
    result = resolve_glyphs(
        text,
        [("key", "datamined"), ("gem", "datamined")],
        room_id="test",
    )
    assert result == [
        {"icon": "key", "confidence": "datamined"},
        {"icon": "steps", "confidence": "datamined"},
        {"icon": "gem", "confidence": "datamined"},
    ]


def test_too_few_ambiguous_raises():
    """Bare glyphs that exhaust the ambiguous list raise ValueError, turning
    a silent mis-decode into a loud failure."""
    text = f"gain {GLYPH_BARE} and {GLYPH_BARE}"
    with pytest.raises(ValueError, match="ran out of ambiguous entries"):
        resolve_glyphs(text, [("key", "datamined")], room_id="double_bare")


def test_too_many_ambiguous_raises():
    """Unused ambiguous entries after the full text scan raise ValueError, so
    over-specified map entries don't silently pad the resolution list."""
    text = f"gain {GLYPH_BARE}"
    with pytest.raises(ValueError, match="unused ambiguous entries"):
        resolve_glyphs(text, [("key", "datamined"), ("gem", "datamined")], room_id="single_bare")


def test_no_glyphs_yields_empty():
    """Text with no glyph characters produces an empty list; callers omit
    glyph_resolution when the result is empty."""
    result = resolve_glyphs("This room counts as 2 BEDROOMS.", ambiguous=[], room_id="bunk_room")
    assert result == []


def test_empty_text_yields_empty():
    """Empty effect text produces an empty list without error."""
    result = resolve_glyphs("", ambiguous=[], room_id="no_effect")
    assert result == []


def test_multiple_tailed_dice_no_ambiguous():
    """Multiple ð² in a single text all decode to dice without consuming any
    ambiguous entries — covers geist_bedroom__ix69's two-dice effect."""
    text = f"+2{GLYPH_DICE}  If you have TOMB today, gain 4{GLYPH_DICE}."
    result = resolve_glyphs(text, ambiguous=[], room_id="geist_bedroom__ix69")
    assert result == [
        {"icon": "dice", "confidence": "datamined"},
        {"icon": "dice", "confidence": "datamined"},
    ]
