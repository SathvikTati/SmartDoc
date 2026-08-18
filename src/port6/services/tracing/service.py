"""Phoenix tracing for the retrieval pipeline.

Every answer is several model calls behind one HTTP response — resolve the
follow-up, plan the tools, validate the evidence, write the expression,
generate the answer — and when one of them misbehaves the logs show the
outcome, not the prompt that caused it. Phoenix records each call as a
span with its prompt, its completion, its latency and its token counts, so
"why did it pick that tool" is a question with an answer.

**This process only emits spans.** It does not run the Phoenix UI. The
server package pulls in scikit-learn, boto3 and a GraphQL stack, and fails
to import on Python 3.11 besides — none of which belongs in an API that
just wants to report what it did. Phoenix runs separately:

    uvx phoenix serve            # then open http://localhost:6006

Off unless `PHOENIX_ENABLED=true`. Tracing is a development aid, and a
collector that is not running should not add a failed connection to every
model call.

Failure here is always swallowed. Observability that can take the service
down with it is worse than none.
"""

from __future__ import annotations

import logging
import os


logger = logging.getLogger(__name__)


DEFAULT_ENDPOINT = "http://localhost:6006/v1/traces"
PROJECT_NAME = "port6"


_configured = False


def is_enabled() -> bool:
    return os.getenv("PHOENIX_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def endpoint() -> str:
    return os.getenv("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_ENDPOINT)


def setup() -> bool:
    """Point the LangChain instrumentor at Phoenix. Safe to call twice."""

    global _configured

    if _configured:
        return True

    if not is_enabled():
        logger.debug("Phoenix tracing is off (set PHOENIX_ENABLED=true)")
        return False

    try:
        from openinference.instrumentation.langchain import (
            LangChainInstrumentor,
        )
        from phoenix.otel import register

        tracer_provider = register(
            project_name=os.getenv("PHOENIX_PROJECT_NAME", PROJECT_NAME),
            endpoint=endpoint(),
            # This module is the only place instrumentation is configured;
            # letting register() also patch things would double every span.
            auto_instrument=False,
            batch=True,
            set_global_tracer_provider=False,
        )

        # One hook covers the whole pipeline: every prompt goes through a
        # LangChain chain, including the LangGraph nodes, so nothing has
        # to be decorated by hand and a new call site is traced for free.
        LangChainInstrumentor().instrument(
            tracer_provider=tracer_provider,
            skip_dep_check=True,
        )

    except Exception as exc:
        # A missing package, an unreachable collector, a version skew —
        # none of it is a reason to fail a question.
        logger.warning("Phoenix tracing could not start: %s", exc)
        return False

    _configured = True

    logger.info("Phoenix tracing on, sending spans to %s", endpoint())

    return True
