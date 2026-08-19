"""Arithmetic, and the sandbox around it.

The expression comes from a model, so it is untrusted input. Half of these
are attacks: `eval` on model output is arbitrary code execution, and the
whole point of the AST walker is that there is no path from an expression
to imports, attributes or arbitrary calls.
"""

import pytest

from port6.services.rag.calculator import (
    MAX_EXPONENT,
    UnsafeExpression,
    calculate,
    format_result,
)


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("22 - 8", 14),
        ("250 * 0.15", 37.5),
        ("(22 + 12) / 2", 17),
        ("22 // 7", 3),
        ("22 % 7", 1),
        ("2 ** 10", 1024),
        ("-5 + 3", -2),
        ("round(22 / 7, 2)", 3.14),
        ("max(22, 26)", 26),
        ("min(22, 26)", 22),
        ("abs(-14)", 14),
        ("sqrt(144)", 12),
        ("floor(3.9)", 3),
        ("ceil(3.1)", 4),
    ],
)
def test_arithmetic(expression, expected):
    assert calculate(expression) == pytest.approx(expected)


# --- the sandbox ------------------------------------------------------

@pytest.mark.parametrize(
    "attack",
    [
        '__import__("os").system("echo pwned")',
        '().__class__.__bases__[0].__subclasses__()',
        'open("/etc/passwd").read()',
        'eval("1+1")',
        'exec("x=1")',
        '__builtins__',
        '(1).__class__',
        'globals()',
        'lambda: 1',
        '[x for x in range(10)]',
        '"a" * 10',
        'True',
    ],
)
def test_nothing_but_arithmetic_gets_through(attack):
    """Each of these is a way `eval` would have executed code."""

    with pytest.raises(UnsafeExpression):
        calculate(attack)


def test_an_unbounded_exponent_cannot_hang_the_process():
    """2 ** 10_000_000 is valid arithmetic and a denial of service."""

    with pytest.raises(UnsafeExpression) as caught:
        calculate(f"2 ** {MAX_EXPONENT + 1}")

    assert "exponent" in str(caught.value)


def test_an_unknown_name_is_refused():
    with pytest.raises(UnsafeExpression):
        calculate("x + 1")


def test_known_constants_are_allowed():
    assert calculate("pi") == pytest.approx(3.14159, abs=1e-4)


def test_an_unknown_function_is_refused():
    with pytest.raises(UnsafeExpression) as caught:
        calculate("system(1)")

    assert "system() is not allowed" in str(caught.value)


@pytest.mark.parametrize("expression", ["", "   ", "22 +", "((1)"])
def test_malformed_input_is_refused_not_crashed(expression):
    with pytest.raises(UnsafeExpression):
        calculate(expression)


def test_a_very_long_expression_is_refused():
    with pytest.raises(UnsafeExpression):
        calculate("1+" * 400 + "1")


# --- presentation -----------------------------------------------------

def test_float_noise_is_not_shown_to_the_user():
    assert format_result(0.1 + 0.2) == "0.3"
    assert format_result(14.0) == "14"
    assert format_result(37.5) == "37.5"


def test_division_by_zero_surfaces_rather_than_crashing():
    with pytest.raises(ZeroDivisionError):
        calculate("1 / 0")


# --- the post-retrieval gate ------------------------------------------

from port6.services.rag.calculator import (  # noqa: E402
    is_bare_literal,
    needs_calculation,
)


class TestNeedsCalculation:
    """The gate decides which questions cost an extra model call."""

    def test_a_question_with_no_numbers_is_not_arithmetic(self):
        assert not needs_calculation("What is the maternity leave policy?")
        assert not needs_calculation("How much annual leave do we get?")
        assert not needs_calculation("Which documents mention probation?")

    def test_two_numbers_are_enough_on_their_own(self):
        assert needs_calculation("What is 15% of the 250 USD cap?")
        assert needs_calculation(
            "My rate is 20 and I worked 6 overtime hours. What is my pay?"
        )

    def test_one_number_needs_a_word_that_implies_a_sum(self):
        assert needs_calculation("I have taken 8 days. How many are left?")
        assert needs_calculation("I have taken 8 days. What is remaining?")

    def test_a_code_that_happens_to_contain_digits_is_not_arithmetic(self):
        """The reason the gate needs an intent word at all."""

        assert not needs_calculation("What is control SEC-4412?")
        assert not needs_calculation("What does FIN-2026-EXP cover?")

    def test_an_empty_question_is_handled(self):
        assert not needs_calculation("")
        assert not needs_calculation(None)


class TestBareLiteral:
    """A model that answers instead of working is not a calculator."""

    def test_a_plain_number_is_rejected(self):
        assert is_bare_literal("32")
        assert is_bare_literal(" 14 ")
        assert is_bare_literal("37.5")

    def test_a_signed_number_is_still_a_literal(self):
        assert is_bare_literal("-5")

    def test_real_working_is_kept(self):
        assert not is_bare_literal("22 - 8")
        assert not is_bare_literal("20 * 1.5 * 6")
        assert not is_bare_literal("250 * 0.15")

    def test_unparseable_text_is_left_to_the_evaluator_to_reject(self):
        assert not is_bare_literal("not an expression")


# --- provenance --------------------------------------------------------

from port6.services.rag.base import RetrievedChunk  # noqa: E402
from port6.services.rag.calculator import (  # noqa: E402
    calculation_chunk,
    contributing_chunks,
)
from port6.services.rag.generation import (  # noqa: E402
    _credit_calculation_sources,
)


def _chunk(number, text):
    return RetrievedChunk(
        number=number,
        chunk_id=f"c{number}",
        document_id="doc",
        filename="hr_policy.md",
        content=text,
    )


class TestContributingChunks:
    """Which documents supplied the numbers in the expression."""

    def test_it_finds_the_chunk_holding_the_figure(self):
        chunks = [
            _chunk(1, "Employees accrue 22 days of paid annual leave."),
            _chunk(2, "Employees receive 12 days of paid sick leave."),
        ]

        assert contributing_chunks("22 - 8", chunks) == ["c1"]

    def test_it_finds_a_formula_the_question_did_not_carry(self):
        chunks = [
            _chunk(1, "Overtime pay = Hourly rate x 1.5 x hours worked."),
            _chunk(2, "Employees accrue 22 days of annual leave."),
        ]

        assert contributing_chunks("20 * 1.5 * 6", chunks) == ["c1"]

    def test_a_longer_number_is_not_a_partial_match(self):
        """Without word boundaries, 22 would match inside 1220."""

        chunks = [_chunk(1, "See reference 1220 for details.")]

        assert contributing_chunks("22 - 8", chunks) == []

    def test_a_decimal_is_not_matched_by_its_leading_digit(self):
        chunks = [_chunk(1, "The multiplier is 1.75 for weekends.")]

        assert contributing_chunks("1 + 2", chunks) == []

    def test_an_earlier_calculation_is_never_a_contributor(self):
        chunks = [
            _chunk(1, "Employees accrue 22 days."),
            calculation_chunk(2, "22 - 8", "14"),
        ]

        assert contributing_chunks("22 - 8", chunks) == ["c1"]

    def test_an_expression_with_no_numbers_contributes_nothing(self):
        assert contributing_chunks("pi", [_chunk(1, "22 days")]) == []


class TestCreditingCalculationSources:
    """Citing the sum has to credit the documents behind it."""

    def test_the_source_of_the_figure_is_credited(self):
        """The bug: hr_policy.md read "unused" in an answer built on it."""

        source = _chunk(1, "Employees accrue 22 days of annual leave.")
        calc = calculation_chunk(2, "22 - 8", "14", derived_from=["c1"])

        credited = _credit_calculation_sources([calc], [source, calc])

        assert [chunk.chunk_id for chunk in credited] == ["calc:22 - 8", "c1"]

    def test_the_model_s_own_numbering_is_left_alone(self):
        """Credited sources are appended, never inserted."""

        source = _chunk(1, "Employees accrue 22 days.")
        other = _chunk(2, "Probation is 3 months.")
        calc = calculation_chunk(3, "22 - 8", "14", derived_from=["c1"])

        credited = _credit_calculation_sources(
            [other, calc],
            [source, other, calc],
        )

        assert [chunk.number for chunk in credited] == [2, 3, 1]

    def test_a_source_already_cited_is_not_duplicated(self):
        source = _chunk(1, "Employees accrue 22 days.")
        calc = calculation_chunk(2, "22 - 8", "14", derived_from=["c1"])

        credited = _credit_calculation_sources(
            [source, calc],
            [source, calc],
        )

        assert len(credited) == 2

    def test_an_uncited_calculation_credits_nothing(self):
        """No marker for the sum means the answer did not rest on it."""

        source = _chunk(1, "Employees accrue 22 days.")
        calc = calculation_chunk(2, "22 - 8", "14", derived_from=["c1"])

        assert _credit_calculation_sources([], [source, calc]) == []

    def test_an_ordinary_answer_is_untouched(self):
        source = _chunk(1, "Employees accrue 22 days.")

        assert _credit_calculation_sources([source], [source]) == [source]


class TestQuestionSuppliedFigures:
    """A number the user typed does not make a document a source."""

    def test_a_figure_only_the_document_has_is_attributed(self):
        chunks = [
            _chunk(1, "Overtime pay = Hourly rate x 1.5 x hours worked."),
            _chunk(2, "Standard hours are 20 per week over 6 days."),
        ]

        question = "My rate is 20 and I worked 6 overtime hours. What is my pay?"

        # Only 1.5 is absent from the question, so only chunk 1 qualifies.
        assert contributing_chunks("20 * 1.5 * 6", chunks, question) == ["c1"]

    def test_without_it_a_shared_digit_would_credit_the_wrong_document(self):
        """The behaviour the question filter exists to prevent."""

        chunks = [
            _chunk(1, "Overtime pay = Hourly rate x 1.5 x hours worked."),
            _chunk(2, "Standard hours are 20 per week over 6 days."),
        ]

        assert contributing_chunks("20 * 1.5 * 6", chunks) == ["c1", "c2"]

    def test_the_entitlement_is_still_credited(self):
        """The 8 is the user's; the 22 is the policy's."""

        chunks = [_chunk(1, "Employees accrue 22 days of annual leave.")]

        question = "I have taken 8 days. How many are remaining?"

        assert contributing_chunks("22 - 8", chunks, question) == ["c1"]

    def test_an_expression_wholly_from_the_question_credits_nothing(self):
        chunks = [_chunk(1, "Employees accrue 22 days of annual leave.")]

        assert contributing_chunks("12 + 30", chunks, "What is 12 + 30?") == []


# --- the worked examples in the prompt ---------------------------------

from port6.services.settings.defaults import CALCULATION_TEMPLATE  # noqa: E402


def _worked_examples(template):
    """The (sources, question, expression) triples the prompt teaches from.

    Read out of the template rather than restated here, so an example that
    is edited is an example that is checked.
    """

    examples = []
    sources = question = None

    for line in template.splitlines():

        line = line.strip()

        if line.startswith("Sources:"):
            # The trailing "Sources:" heading introduces {context}, not an
            # example, so it carries no text of its own.
            sources = line[len("Sources:"):].strip() or None
            question = None

        elif line.startswith("Question:"):
            question = line[len("Question:"):].strip()

            # Likewise the closing "Question: {question}".
            if question == "{question}":
                question = None

        elif line and sources and question:
            examples.append((sources, question, line))
            sources = question = None

    return examples


class TestPromptExamples:
    """A worked example is the lesson, so a wrong one teaches wrong.

    The tiered case is the one that matters here: a rate that changes
    partway through used to come back as its first band alone — 6 Saturday
    hours priced as 4 — which is well-formed arithmetic and so passes every
    other guard in this module.
    """

    def test_every_example_is_arithmetic_the_evaluator_accepts(self):
        for sources, question, expression in _worked_examples(
            CALCULATION_TEMPLATE
        ):
            if expression == "NONE":
                continue

            # Raises UnsafeExpression if the prompt teaches something the
            # calculator would then refuse.
            calculate(expression)

    def test_no_example_hands_over_an_answer_instead_of_working(self):
        for sources, question, expression in _worked_examples(
            CALCULATION_TEMPLATE
        ):
            if expression == "NONE":
                continue

            assert not is_bare_literal(expression), expression

    def test_a_banded_rate_is_demonstrated_and_adds_up(self):
        banded = [
            (sources, question, expression)
            for sources, question, expression in _worked_examples(
                CALCULATION_TEMPLATE
            )
            if "thereafter" in sources
        ]

        assert banded, "the prompt no longer shows a rate that changes"

        for sources, question, expression in banded:
            # One term per band, summed — not the first band alone.
            assert "+" in expression, expression
            assert calculate(expression) == pytest.approx(
                10000 * 0.45 + 2000 * 0.25
            )

    def test_the_banded_example_spends_the_whole_quantity(self):
        """10,000 + 2,000, against the 12,000 the question gave."""

        for sources, question, expression in _worked_examples(
            CALCULATION_TEMPLATE
        ):
            if "thereafter" not in sources:
                continue

            assert "12,000" in question

            quantities = [
                node
                for node in (10000, 2000)
                if str(node) in expression.replace(",", "")
            ]

            assert sum(quantities) == 12000
