"""Greetings answered directly, and real questions left alone.

The dangerous failure here is the false positive: a real question quietly
answered with "how can I help?" instead of being retrieved for. Most of
these tests are about what must *not* match.
"""

from port6.services.rag.smalltalk import (
    MAX_CHARACTERS,
    classify,
    normalise,
)


class TestNormalise:

    def test_punctuation_and_case_are_stripped(self):
        assert normalise("Hello!!") == "hello"
        assert normalise("  HEY   there  ") == "hey there"

    def test_emoji_and_symbols_do_not_defeat_a_match(self):
        assert normalise("hi :)") == "hi"

    def test_an_empty_message_normalises_to_nothing(self):
        assert normalise("") == ""
        assert normalise("...") == ""


class TestGreetings:

    def test_the_common_openers_are_recognised(self):
        for phrase in ["hi", "Hello", "hey there", "Good morning", "howdy"]:
            assert classify(phrase).kind == "greeting", phrase

    def test_thanks_is_acknowledged(self):
        for phrase in ["thanks", "Thank you!", "cheers", "got it"]:
            assert classify(phrase).kind == "thanks", phrase

    def test_a_farewell_is_recognised(self):
        assert classify("bye").kind == "farewell"

    def test_asking_what_it_does_gets_the_capabilities(self):
        for phrase in ["what can you do?", "who are you", "help"]:
            assert classify(phrase).kind == "capability", phrase

    def test_the_greeting_reply_says_what_to_ask(self):
        answer = classify("hello").answer

        assert "documents" in answer
        assert "annual leave" in answer


class TestWhatMustNotMatch:
    """Every one of these has to reach retrieval."""

    def test_a_greeting_attached_to_a_real_question_is_a_question(self):
        assert classify("hi, how much annual leave do we get?") is None
        assert classify("hello, what is control SEC-4412?") is None

    def test_ordinary_questions_are_untouched(self):
        for phrase in [
            "How much annual leave do employees get?",
            "What is control SEC-4412?",
            "Which documents mention probation?",
            "What is the grievance procedure?",
        ]:
            assert classify(phrase) is None, phrase

    def test_help_inside_a_sentence_is_not_a_help_request(self):
        assert classify("help me understand the grievance procedure") is None

    def test_a_long_message_is_never_small_talk(self):
        assert classify("hello " * MAX_CHARACTERS) is None

    def test_empty_and_blank_are_not_small_talk(self):
        assert classify("") is None
        assert classify("   ") is None
        assert classify(None) is None

    def test_a_word_containing_a_greeting_does_not_match(self):
        """"highest" starts with "hi"; matching is on the whole message."""

        assert classify("highest") is None
        assert classify("hey day policy") is None
