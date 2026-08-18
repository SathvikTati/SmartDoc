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
