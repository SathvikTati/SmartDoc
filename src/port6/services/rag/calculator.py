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
import logging
import math
import operator
import re


logger = logging.getLogger(__name__)


# Not a row in the documents table, so nothing links to it as one. The web
# uses the same trick with "web".
CALCULATION_DOCUMENT_ID = "calculation"


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


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# Words that turn numbers in a question into a sum to be done. A question
# with two numbers is treated as arithmetic on its own; one number needs a
# word like these to distinguish "I have taken 8, how many are left?" from
# "What is control SEC-4412?".
_ARITHMETIC_INTENT = (
    "remaining",
    "left",
    "how many",
    "how much",
    "total",
    "sum",
    "difference",
    "percent",
    "%",
    "average",
    "balance",
    "altogether",
    "combined",
    "minus",
    "plus",
    "times",
    "pro-rated",
    "prorated",
    "pro rata",
)


def needs_calculation(question: str) -> bool:
    """Whether a question is worth spending a model call on.

    Cheap and deliberately narrow. Every question that passes costs one
    extra call to write the expression, and most questions are not
    arithmetic — so the gate is a filter, not a classifier. It errs toward
    letting a question through, because the expression step returns NONE
    for anything it cannot build.
    """

    lowered = (question or "").lower()

    numbers = _NUMBER.findall(lowered)

    if not numbers:
        return False

    if len(numbers) >= 2:
        return True

    return any(word in lowered for word in _ARITHMETIC_INTENT)


async def extract_expression(
    question: str,
    context: str = "",
) -> str | None:
    """Pull an arithmetic expression out of a question and its sources.

    The sources matter as much as the question. "I have taken 8 days, how
    many are left?" is not solvable from the question alone — the 22-day
    entitlement is in the document — and an overtime question is worse
    still, because the ×1.5 multiplier only exists in the policy. Asked
    without the sources, the model either guesses or drops the term.

    Returns None when there is no arithmetic to do.
    """

    from port6.services.llm.service import get_chat_model
    from port6.services.settings.service import get_prompt

    try:
        chain = get_prompt("calculation_expression") | get_chat_model()
        response = await chain.ainvoke(
            {
                "question": question,
                "context": context,
            }
        )

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


def is_bare_literal(expression: str) -> bool:
    """True when the "expression" is just a number.

    The model was asked for working and returned an answer — "32" rather
    than "22 + 10". That is worth rejecting rather than passing on: the
    figure has no derivation behind it, so it is the model's arithmetic
    wearing a calculator's label, which is exactly what this module exists
    to avoid. Better to offer no calculation than a laundered guess.
    """

    try:
        tree = ast.parse((expression or "").strip(), mode="eval")

    except SyntaxError:
        return False

    node = tree.body

    # -5 is still a literal, so unwrap the sign before judging.
    while isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.UAdd, ast.USub)
    ):
        node = node.operand

    return isinstance(node, ast.Constant)


def contributing_chunks(
    expression: str,
    chunks: list,
    question: str = "",
) -> list[str]:
    """Which retrieved chunks supplied the numbers in the expression.

    Matched on the literals themselves. `22 - 8` against a chunk reading
    "Employees accrue 22 days" is an exact, checkable link — far better
    than asking the model to report its own sources, which costs another
    call and can be invented.

    A literal already in the question is skipped, because the model was
    given only the question and the sources: a number absent from the
    question can only have come from a document, while one present in it
    may have come from either. Attributing the ambiguous ones marks
    documents as load-bearing on a digit they happen to share — an
    overtime question carrying "20" and "6" lit up three unrelated
    chunks before this. Under-crediting a source the user quoted is the
    cheaper mistake: the claim this makes stays true.

    The boundaries are the fiddly part. Without them the 22 in `22 - 8`
    matches inside 1220, and the 1 in `1 + 2` matches the 1 of 1.75 — so a
    literal is rejected when a digit sits on either side of it, or when a
    decimal point and a digit follow. A trailing full stop is still fine,
    because "accrue 22." ends a sentence rather than a number.
    """

    from_question = set(_NUMBER.findall(question or ""))

    literals = set(_NUMBER.findall(expression)) - from_question

    if not literals:
        return []

    contributors = []

    for chunk in chunks:

        if chunk.document_id == CALCULATION_DOCUMENT_ID:
            continue

        content = chunk.content or ""

        if any(
            re.search(
                rf"(?<![\d.]){re.escape(literal)}(?!\d|\.\d)",
                content,
            )
            for literal in literals
        ):
            contributors.append(chunk.chunk_id)

    return contributors


def calculation_chunk(
    number: int,
    expression: str,
    result: str,
    derived_from: list[str] | None = None,
):
    """The worked sum, as a source the answer can cite."""

    from port6.services.rag.base import RetrievedChunk

    return RetrievedChunk(
        number=number,
        chunk_id=f"calc:{expression}",
        document_id=CALCULATION_DOCUMENT_ID,
        filename="calculator",
        content=f"{expression} = {result}",
        derived_from=derived_from or [],
        sources=["calculation"],
    )


async def augment_with_calculation(
    question: str,
    chunks: list,
) -> list:
    """Add the worked sum to the sources, when the answer needs one.

    This runs after retrieval rather than instead of it, which is the
    whole point. Retrieval finds "22 days accrued" and the policy's
    overtime formula; only then is there enough on the table to write the
    expression. Asking for the expression first — which is what the
    `calculate` tool does when the agent picks it — means writing it from
    the question alone, and a question rarely carries the rate.

    The result is offered as one more numbered source. It is not forced
    into the answer: if the model does not need it, it does not cite it.
    Failure is silent by design — a question that turns out not to be
    arithmetic must not lose its documents over it.
    """

    from port6.services.rag.generation import build_context
    from port6.services.settings.service import get_setting

    if not chunks or not get_setting("calculation.enabled"):
        return chunks

    # The agent may already have run the tool on a question that was
    # itself an expression, in which case the sum is on the table and
    # doing it again would give the model two sources for one figure.
    #
    # It arrives without provenance, though: the tool runs before
    # retrieval, so there was nothing to attribute it to. Now there is.
    existing = [
        chunk
        for chunk in chunks
        if chunk.document_id == CALCULATION_DOCUMENT_ID
    ]

    if existing:

        for chunk in existing:

            if chunk.derived_from:
                continue

            chunk.derived_from = contributing_chunks(
                chunk.content.split("=")[0],
                chunks,
                question,
            )

        return chunks

    if not needs_calculation(question):
        return chunks

    expression = await extract_expression(question, build_context(chunks))

    if not expression:
        return chunks

    if is_bare_literal(expression):
        logger.info(
            "Ignoring bare literal %r: the model answered instead of "
            "writing an expression",
            expression[:40],
        )
        return chunks

    try:
        value = calculate(expression)

    except UnsafeExpression as exc:
        # The model wrote something that is not arithmetic. That is a
        # normal outcome for a question that only looked numeric.
        logger.info(
            "No usable expression for %r (%s): %s",
            question[:60],
            expression[:40],
            exc,
        )
        return chunks

    result = format_result(value)

    logger.info("Calculated %s = %s", expression, result)

    return chunks + [
        calculation_chunk(
            len(chunks) + 1,
            expression,
            result,
            derived_from=contributing_chunks(
                expression,
                chunks,
                question,
            ),
        )
    ]
