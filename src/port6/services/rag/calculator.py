"""Arithmetic, evaluated safely.

Language models are unreliable at arithmetic and confidently wrong when
they get it wrong, which is the worst combination in an answer that cites
a policy. Retrieval can find "22 days accrued" and "8 days taken"; working
out that 14 remain should not be left to token prediction.

**This never calls `eval`.** The expression comes from a model, which means
it is untrusted input, and `eval` on untrusted input is arbitrary code
execution — `__import__("os").system(...)` is a one-liner. Instead the
expression is parsed to an AST and walked, and anything not on the allow
list below is rejected. There is no path from an expression to attribute
access, imports, names or arbitrary calls.
"""

from __future__ import annotations

import ast
import math
import operator


class UnsafeExpression(ValueError):
    """The expression contained something not on the allow list."""


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
}

_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

# 2 ** 10_000_000 is a valid expression that will hang the process and
# exhaust memory, so exponents are bounded rather than trusted.
MAX_EXPONENT = 1000
MAX_EXPRESSION_LENGTH = 500


def _evaluate(node):

    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(
            node.value, (int, float)
        ):
            raise UnsafeExpression("only numbers are allowed")
        return node.value

    if isinstance(node, ast.BinOp):
        handler = _BINARY.get(type(node.op))

        if handler is None:
            raise UnsafeExpression(
                f"operator {type(node.op).__name__} is not allowed"
            )

        left = _evaluate(node.left)
        right = _evaluate(node.right)

        if handler is operator.pow and abs(right) > MAX_EXPONENT:
            raise UnsafeExpression(
                f"exponent above {MAX_EXPONENT} is not allowed"
            )

        return handler(left, right)

    if isinstance(node, ast.UnaryOp):
        handler = _UNARY.get(type(node.op))

        if handler is None:
            raise UnsafeExpression(
                f"operator {type(node.op).__name__} is not allowed"
            )

        return handler(_evaluate(node.operand))

    if isinstance(node, ast.Call):
        # Only a bare name from the allow list may be called. This is what
        # blocks `__import__(...)` and any attribute call such as
        # `().__class__.__bases__[0].__subclasses__()`.
        if not isinstance(node.func, ast.Name):
            raise UnsafeExpression("only named functions may be called")

        function = _FUNCTIONS.get(node.func.id)

        if function is None:
            raise UnsafeExpression(f"{node.func.id}() is not allowed")

        if node.keywords:
            raise UnsafeExpression("keyword arguments are not allowed")

        return function(*[_evaluate(argument) for argument in node.args])

    if isinstance(node, ast.Name):
        if node.id not in _CONSTANTS:
            raise UnsafeExpression(f"{node.id!r} is not a known value")

        return _CONSTANTS[node.id]

    # Tuples exist so min(1, 2) style calls with a sequence still work.
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_evaluate(element) for element in node.elts]

    raise UnsafeExpression(
        f"{type(node).__name__} is not allowed in an expression"
    )


def calculate(expression: str) -> float | int:
    """Evaluate an arithmetic expression. Raises UnsafeExpression if not."""

    expression = (expression or "").strip()

    if not expression:
        raise UnsafeExpression("the expression is empty")

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpression("the expression is too long")

    try:
        tree = ast.parse(expression, mode="eval")

    except SyntaxError as exc:
        raise UnsafeExpression(f"could not parse the expression: {exc.msg}")

    return _evaluate(tree)


def format_result(value) -> str:
    """Render a result without float noise like 13.999999999999998."""

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)

        rounded = round(value, 10)

        if rounded == int(rounded):
            return str(int(rounded))

        return f"{rounded:g}"

    return str(value)


async def extract_expression(question: str) -> str | None:
    """Pull an arithmetic expression out of a sentence.

    The agent hands every tool the raw question — correct for retrieval,
    useless for arithmetic. Rather than complicate the planner into
    emitting per-tool arguments (which the local model already struggles
    to format), the tool recovers the expression itself.

    Returns None when there is no arithmetic to do.
    """

    from port6.services.llm.service import get_chat_model
    from port6.services.settings.service import get_prompt

    try:
        chain = get_prompt("calculation_expression") | get_chat_model()
        response = await chain.ainvoke({"question": question})

        text = response.content

        if not isinstance(text, str):
            text = str(text)

        # Models wrap expressions in backticks and prose despite being
        # told not to; take the first line and strip the decoration.
        text = text.strip().strip("`").splitlines()[0].strip()

        if text.lower().startswith("none") or not text:
            return None

        # "22 - 8 = 14" -> "22 - 8"
        if "=" in text:
            text = text.split("=")[0].strip()

        return text or None

    except Exception:
        return None
