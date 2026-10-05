"""Live captions publish one recognition; overlap is only deduplicated."""

from civiccast.captions.models import CaptionHypothesis, CaptionWord
from civiccast.captions.stabilize import CaptionStabilizer


def hypothesis(text, start, end, words=None, confidence=1):
    return CaptionHypothesis(
        source_id="live",
        text=text,
        start_seconds=start,
        end_seconds=end,
        audio_window_start_seconds=start,
        audio_window_end_seconds=end,
        words=words,
        confidence=confidence,
    )


def test_first_pass_publishes_even_with_high_offline_confirmation_setting():
    s = CaptionStabilizer(live=True, stable_windows=9)
    cues = s.observe(hypothesis("Thank you.", 0, 5, words=[]))
    assert [c.text for c in cues] == ["Thank you."]
    assert not s.flush()
    assert not s.expired_unconfirmed()


def test_timed_overlap_publishes_new_words_without_agreement():
    s = CaptionStabilizer(live=True)
    first = hypothesis(
        "motion carries",
        0,
        10,
        [
            CaptionWord(text="motion", start_seconds=6, end_seconds=7),
            CaptionWord(text="carries", start_seconds=8, end_seconds=9),
        ],
    )
    assert [c.text for c in s.observe(first)] == ["motion carries"]
    later = hypothesis(
        "motion fails next item",
        5,
        15,
        [
            CaptionWord(text="motion", start_seconds=6.1, end_seconds=7.1),
            CaptionWord(text="fails", start_seconds=8, end_seconds=9),
            CaptionWord(text="next", start_seconds=11, end_seconds=12),
            CaptionWord(text="item", start_seconds=12, end_seconds=13),
        ],
    )
    assert [c.text for c in s.observe(later)] == ["next item"]
    assert not s.observe(later)


def test_untimed_overlap_strips_already_aired_suffix_only():
    s = CaptionStabilizer(live=True)
    assert s.observe(hypothesis("opening motion carries", 0, 9))
    cues = s.observe(hypothesis("motion carries next item", 5, 14))
    assert [c.text for c in cues] == ["next item"]
    assert not s.observe(hypothesis("motion carries next item", 5, 14))
    assert s.observe(hypothesis("next item", 20, 25))


def test_zero_duration_word_uses_audio_bounds_and_low_confidence_still_airs():
    s = CaptionStabilizer(live=True)
    cues = s.observe(
        hypothesis(
            "Thanks.",
            0,
            5,
            [
                CaptionWord(text="Thanks.", start_seconds=0, end_seconds=0),
            ],
            confidence=0.2,
        )
    )
    assert cues[0].text == "Thanks."
    assert cues[0].end_seconds > cues[0].start_seconds
    assert cues[0].low_confidence


def test_advancing_unrelated_text_is_not_withheld_and_old_window_cannot_replay():
    s = CaptionStabilizer(live=True)
    assert s.observe(hypothesis("first sentence", 0, 9))
    assert s.observe(hypothesis("changed recognition", 5, 14))
    assert not s.observe(hypothesis("stale recognition", 0, 9))
    assert not s.observe(hypothesis("   ", 15, 20))


def test_mixed_zero_and_positive_duration_words_preserve_both_words():
    s = CaptionStabilizer(live=True)
    cues = s.observe(
        hypothesis(
            "Thank you",
            0,
            10,
            [
                CaptionWord(text="Thank", start_seconds=0, end_seconds=0),
                CaptionWord(text="you", start_seconds=0, end_seconds=1),
            ],
        )
    )
    assert cues[0].text == "Thank you"


def test_previously_aired_crossing_word_is_not_repeated():
    s = CaptionStabilizer(live=True)
    assert s.observe(
        hypothesis(
            "motion",
            0,
            10,
            [
                CaptionWord(text="motion", start_seconds=9.5, end_seconds=10),
            ],
        )
    )
    cues = s.observe(
        hypothesis(
            "motion carries",
            5,
            15,
            [
                CaptionWord(text="motion", start_seconds=9.5, end_seconds=10.3),
                CaptionWord(text="carries", start_seconds=11, end_seconds=12),
            ],
        )
    )
    assert cues[0].text == "carries"


def test_new_crossing_word_does_not_need_to_match_previous_recognition():
    s = CaptionStabilizer(live=True)
    assert s.observe(
        hypothesis(
            "the",
            0,
            10,
            [
                CaptionWord(text="the", start_seconds=8, end_seconds=9),
            ],
        )
    )
    cues = s.observe(
        hypothesis(
            "motion carries",
            5,
            15,
            [
                CaptionWord(text="motion", start_seconds=9.5, end_seconds=10.3),
                CaptionWord(text="carries", start_seconds=11, end_seconds=12),
            ],
        )
    )
    assert cues[0].text == "motion carries"


def test_whistle_text_without_word_metadata_airs_instead_of_falling_back():
    from civiccast.captions.models import AudioChunk
    from civiccast.captions.whistle import _hypotheses

    audio = AudioChunk(
        chunk_id="public-tap-1",
        start_seconds=0,
        end_seconds=5,
        sample_rate_hz=16000,
        pcm_s16le=b"\x00\x00" * 80000,
    )
    hypotheses = _hypotheses(audio, {"text": "Thank you.", "words": []})
    cues = CaptionStabilizer(live=True).observe(hypotheses[0])
    assert cues[0].text == "Thank you."
    assert (cues[0].start_seconds, cues[0].end_seconds) == (0, 5)


def test_distinct_repeated_word_crossing_boundary_is_preserved():
    s = CaptionStabilizer(live=True)
    assert s.observe(
        hypothesis(
            "yes",
            0,
            10,
            [
                CaptionWord(text="yes", start_seconds=8, end_seconds=9),
            ],
        )
    )
    cues = s.observe(
        hypothesis(
            "yes proceed",
            5,
            15,
            [
                CaptionWord(text="yes", start_seconds=9.8, end_seconds=10.3),
                CaptionWord(text="proceed", start_seconds=11, end_seconds=12),
            ],
        )
    )
    assert cues[0].text == "yes proceed"
