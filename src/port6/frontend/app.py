"""Streamlit frontend for PORT-6.

Run with:

    streamlit run src/port6/frontend/app.py

Set PORT6_API_URL if the API is not on http://localhost:8000.
"""

from __future__ import annotations

import html
import re
import time

import streamlit as st

from port6.frontend import api


MODES = {
    "naive": {
        "label": "1 · Naive RAG",
        "help": "Vector search only. The baseline.",
    },
    "hybrid": {
        "label": "2 · Hybrid + Hierarchical",
        "help": (
            "Semantic + BM25 fused with RRF, narrowed "
            "document → section → chunk."
        ),
    },
    "agentic": {
        "label": "3 · Agentic (LangGraph)",
        "help": (
            "An agent plans which retrieval tools to use, then "
            "validates the evidence before answering."
        ),
    },
}


# Mirrors the upload section of config.yaml. Shown as guidance only; the API
# remains the authority and rejects anything outside the limits.
MAX_FILES = 5
MAX_FILE_SIZE_MB = 5

ACCEPTED_EXTENSIONS = [
    "pdf",
    "docx",
    "doc",
    "txt",
    "md",
]

PENDING_STATUSES = (
    "UPLOADED",
    "PROCESSING",
)

STATUS_ICONS = {
    "READY": "🟢",
    "PROCESSING": "🔵",
    "UPLOADED": "⚪",
    "FAILED": "🔴",
}

CITATION_PATTERN = re.compile(r"\[([\d\s,]+)\]")


STYLES = """
<style>
.p6-answer {
    font-size: 1.02rem;
    line-height: 1.7;
}
.p6-cite {
    display: inline-block;
    min-width: 1.15em;
    padding: 0 0.35em;
    margin: 0 0.12em;
    border-radius: 0.7em;
    background: rgba(56, 139, 253, 0.18);
    border: 1px solid rgba(56, 139, 253, 0.45);
    font-size: 0.72em;
    font-weight: 600;
    line-height: 1.6;
    text-align: center;
    vertical-align: super;
}
.p6-cite-dead {
    background: rgba(128, 128, 128, 0.12);
    border: 1px dashed rgba(128, 128, 128, 0.5);
    opacity: 0.65;
}
.p6-chunk {
    padding: 0.6rem 0.8rem;
    border-radius: 0.4rem;
    background: rgba(128, 128, 128, 0.09);
    border-left: 3px solid rgba(56, 139, 253, 0.55);
    white-space: pre-wrap;
    font-size: 0.9rem;
    line-height: 1.55;
}
.p6-meta {
    opacity: 0.7;
    font-size: 0.85rem;
}
</style>
"""


# -------------------------------------------------------------------
# Rendering helpers
# -------------------------------------------------------------------

def render_answer_html(
    answer: str,
    citations: list[dict],
) -> str:
    """Escape the answer and turn its [n] markers into superscript pills.

    The API already drops citations whose source does not exist, but the
    answer text still contains those markers. They are rendered muted rather
    than removed, so the reader can see the model referenced something that
    could not be resolved instead of silently losing it.
    """

    valid_numbers = {
        citation["number"]
        for citation in citations
    }

    escaped = html.escape(answer)

    def replace(match: re.Match) -> str:

        parts = [
            part.strip()
            for part in match.group(1).split(",")
        ]

        if not all(part.isdigit() for part in parts):
            return match.group(0)

        pills = []

        for part in parts:

            number = int(part)

            if number in valid_numbers:
                pills.append(
                    f'<span class="p6-cite" '
                    f'title="Source {number}">{number}</span>'
                )

            else:
                pills.append(
                    f'<span class="p6-cite p6-cite-dead" '
                    f'title="No matching source was returned">'
                    f'{number}</span>'
                )

        return "".join(pills)

    return (
        '<div class="p6-answer">'
        + CITATION_PATTERN.sub(replace, escaped)
        + "</div>"
    )


def citation_label(
    chunk: dict,
) -> str:
    """e.g. "HR Policy, Section 1.2 Maternity Leave, Page 12"."""

    parts = [
        chunk.get("filename") or "unknown"
    ]

    if chunk.get("section_title"):
        parts.append(f"Section {chunk['section_title']}")

    if chunk.get("page_number") is not None:
        parts.append(f"Page {chunk['page_number']}")

    return ", ".join(parts)


def render_source(
    source: dict,
    was_cited: bool,
) -> None:

    label = (
        f"{'📌' if was_cited else '　'} "
        f"[{source['number']}] {citation_label(source)}"
    )

    origin = source.get("sources") or []

    if origin:
        label += f" · {'+'.join(origin)}"

    score = source.get("score")

    if score is not None:
        label += f" · dist {score:.4f}"

    with st.expander(
        label,
        expanded=was_cited,
    ):
        st.markdown(
            '<div class="p6-chunk">'
            + html.escape(source["content"])
            + "</div>",
            unsafe_allow_html=True,
        )

        facts = [
            f"chunk_id: `{source.get('chunk_id')}`",
            f"document_id: `{source.get('document_id')}`",
        ]

        if source.get("section_path"):
            facts.append(f"section path: {source['section_path']}")

        if source.get("fused_score") is not None:
            ranks = []

            if source.get("semantic_rank"):
                ranks.append(f"semantic #{source['semantic_rank']}")

            if source.get("keyword_rank"):
                ranks.append(f"keyword #{source['keyword_rank']}")

            facts.append(
                f"RRF {source['fused_score']:.5f}"
                + (f" ({', '.join(ranks)})" if ranks else "")
            )

        st.caption(" · ".join(facts))


def render_retrieval_trace(
    response: dict,
) -> None:
    """Show how the answer was reached: stages, documents, sections, tools."""

    debug = response.get("debug") or {}

    stages = debug.get("stages") or []

    header = (
        f"🔎 Retrieval trace — {response.get('retrieval_method', '')}"
    )

    # A cached answer says so before the trace is opened. Reuse that the
    # reader cannot see is the one way the cache could mislead — and a
    # similarity hit answered a question that was not quite the one asked,
    # which is worth more than a footnote.
    cache = (response.get("metadata") or {}).get("cache")

    if cache:
        if cache.get("hit") == "semantic":
            st.info(
                f"↺ Reused the answer to a similarly worded question — "
                f"\u201c{cache.get('question')}\u201d — at "
                f"{cache.get('similarity')} similarity. Originally answered "
                f"in {(cache.get('original_latency_ms') or 0) / 1000:.2f}s.",
                icon="⚠️",
            )
        else:
            st.success(
                f"↺ Answered from cache. The same question was first "
                f"answered in "
                f"{(cache.get('original_latency_ms') or 0) / 1000:.2f}s.",
                icon="⚡",
            )

    with st.expander(header, expanded=False):

        top = st.columns(3)

        with top[0]:
            # This lookup, not the run that produced the answer — the
            # original figure is shown as the delta beside it.
            st.metric(
                "Latency",
                f"{(response.get('latency_ms') or 0) / 1000:.2f}s",
                delta=(
                    f"was {(cache['original_latency_ms'] or 0) / 1000:.2f}s"
                    if cache and cache.get("original_latency_ms") is not None
                    else None
                ),
                delta_color="off",
            )

        with top[1]:
            st.metric(
                "Chunks used",
                len(response.get("retrieved_chunks") or []),
            )

        with top[2]:
            st.metric(
                "Citations",
                len(response.get("citations") or []),
            )

        # Agentic: which tools were chosen, and why.
        tools_used = debug.get("tools_used") or []

        if tools_used:
            st.markdown("**Tools used:**")
            for position, tool in enumerate(tools_used, start=1):
                st.markdown(f"{position}. `{tool}`")

            if debug.get("plan_reason"):
                st.caption(f"Plan: {debug['plan_reason']}")

        validation = debug.get("validation_result")

        if validation:
            icon = "✅" if validation.get("sufficient") else "⚠️"
            st.markdown(
                f"**Evidence validation:** {icon} "
                f"{validation.get('reason')} "
                f"_(via {validation.get('method')})_"
            )

        if stages:
            st.markdown("**Pipeline stages:**")
            for stage in stages:
                detail = stage.get("detail", "")
                results = stage.get("results")
                suffix = f" → {results}" if results is not None else ""
                st.markdown(
                    f"- `{stage['name']}` {detail}{suffix}"
                )

        documents = debug.get("retrieved_documents") or []

        if documents:
            st.markdown("**Documents selected (stage 1):**")
            for document in documents:
                st.markdown(
                    f"- {document['filename']}"
                )

        sections = debug.get("retrieved_sections") or []

        if sections:
            st.markdown("**Sections selected (stage 2):**")
            for section in sections:
                st.markdown(
                    f"- {section.get('section_path') or section.get('section_id')}"
                )

        semantic = debug.get("semantic_matches") or []
        keyword = debug.get("keyword_matches") or []
        both = debug.get("matched_by_both") or []

        if semantic or keyword:
            columns = st.columns(2)

            with columns[0]:
                st.markdown(f"**Semantic matches ({len(semantic)})**")
                for match in semantic[:8]:
                    st.caption(
                        f"{match.get('filename')} · "
                        f"{match.get('section') or '—'}"
                    )

            with columns[1]:
                st.markdown(f"**Keyword/BM25 matches ({len(keyword)})**")
                for match in keyword[:8]:
                    st.caption(
                        f"{match.get('filename')} · "
                        f"{match.get('section') or '—'}"
                    )

            if both:
                st.markdown(
                    f"**Found by both retrievers ({len(both)})** — "
                    "these rank highest after fusion"
                )
                for match in both:
                    st.caption(
                        f"{match.get('filename')} · "
                        f"{match.get('section') or '—'} · "
                        f"RRF {match.get('fused_score')}"
                    )


def render_response(
    response: dict,
) -> None:

    citations = response.get("citations") or []
    sources = response.get("retrieved_chunks") or []

    if response.get("answered"):
        st.markdown(
            render_answer_html(
                response["answer"],
                citations,
            ),
            unsafe_allow_html=True,
        )

    else:
        # No answer was found. Showing the retrieved chunks anyway helps the
        # user see what the library did contain.
        st.info(response["answer"])

    render_retrieval_trace(response)

    if not sources:
        return

    cited_numbers = {
        citation["number"]
        for citation in citations
    }

    if citations:
        st.markdown(
            f"**Cited {len(cited_numbers)} of "
            f"{len(sources)} retrieved chunks**"
        )

    else:
        st.markdown(
            f"**{len(sources)} retrieved chunks** "
            "(none referenced in the answer)"
        )

    for source in sources:
        render_source(
            source,
            source["number"] in cited_numbers,
        )


# -------------------------------------------------------------------
# Pages
# -------------------------------------------------------------------

def page_ask(
    top_k: int,
    mode: str,
) -> None:

    st.subheader("Ask the document library")

    st.caption(
        f"**{MODES[mode]['label']}** — {MODES[mode]['help']} "
        "Every statement is marked with the source it came from."
    )

    history = st.session_state.setdefault(
        "ask_history",
        [],
    )

    for turn in history:

        with st.chat_message("user"):
            st.write(f"{turn['question']}  \n*({turn['mode']})*")

        with st.chat_message("assistant"):
            render_response(turn["response"])

    question = st.chat_input(
        "Ask a question about your documents"
    )

    if not question:
        return

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):

        with st.spinner(
            f"Running {MODES[mode]['label']} retrieval…"
        ):

            try:
                response = api.ask(
                    question,
                    top_k=top_k,
                    mode=mode,
                )

            except api.ApiError as exc:
                st.error(str(exc))
                return

        render_response(response)

    history.append(
        {
            "question": question,
            "mode": MODES[mode]["label"],
            "response": response,
        }
    )


def page_compare(top_k: int) -> None:

    st.subheader("Compare retrieval modes")

    st.caption(
        "Runs the same question through each mode so the difference in "
        "retrieval quality is visible side by side. Modes run one after "
        "another against a local model, so this takes a while."
    )

    st.markdown(
        "Try a question that turns on an exact term, for example "
        "*What is control SEC-4412?* — keyword search finds codes that "
        "embeddings alone tend to miss."
    )

    question = st.text_input(
        "Question",
        key="compare_question",
    )

    selected = st.multiselect(
        "Modes",
        options=list(MODES),
        default=list(MODES),
        format_func=lambda mode: MODES[mode]["label"],
    )

    if not question or not selected:
        return

    if not st.button("Run comparison", type="primary"):
        return

    with st.spinner(
        f"Running {len(selected)} pipelines…"
    ):
        try:
            payload = api.compare(
                question,
                top_k=top_k,
                modes=selected,
            )

        except api.ApiError as exc:
            st.error(str(exc))
            return

    results = payload.get("results") or {}

    summary = []

    for mode in selected:

        result = results.get(mode)

        if not result:
            continue

        documents = sorted(
            {
                chunk.get("filename")
                for chunk in (result.get("retrieved_chunks") or [])
            }
        )

        summary.append(
            {
                "Mode": MODES[mode]["label"],
                "Answered": "yes" if result.get("answered") else "no",
                "Citations": len(result.get("citations") or []),
                "Chunks": len(result.get("retrieved_chunks") or []),
                "Documents drawn on": len(documents),
                "Latency (s)": round(
                    (result.get("latency_ms") or 0) / 1000,
                    2,
                ),
            }
        )

    if summary:
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
        )

    for mode in selected:

        result = results.get(mode)

        if not result:
            continue

        st.divider()
        st.markdown(f"### {MODES[mode]['label']}")
        render_response(result)


def page_library() -> None:

    st.subheader("Document library")

    try:
        documents = api.list_documents()

    except api.ApiError as exc:
        st.error(str(exc))
        return

    if not documents:
        st.info(
            "No documents yet. Add some on the Upload tab."
        )
        return

    pending = [
        document
        for document in documents
        if document["status"] in PENDING_STATUSES
    ]

    header, refresh = st.columns([4, 1])

    with header:
        st.caption(
            f"{len(documents)} document(s)"
            + (
                f" · {len(pending)} still processing"
                if pending
                else ""
            )
        )

    with refresh:
        if st.button(
            "Refresh",
            use_container_width=True,
        ):
            st.rerun()

    for document in documents:

        icon = STATUS_ICONS.get(
            document["status"],
            "⚪",
        )

        title = document["filename"]

        with st.expander(
            f"{icon} {title} — {document['status']}"
        ):

            st.markdown(
                '<div class="p6-meta">'
                f"{document['filename']} · "
                f"{document['size_bytes']:,} bytes · "
                f"{document['file_type']} · "
                f"uploaded {document['created_at'][:19].replace('T', ' ')}"
                "</div>",
                unsafe_allow_html=True,
            )

            if document["status"] == "FAILED":
                st.error(
                    document.get("error_message")
                    or "Processing failed."
                )

            summary = document.get("summary")

            if summary:
                st.markdown("**Summary**")
                st.write(summary)

            elif document["status"] == "READY":
                st.caption(
                    "No summary stored for this document."
                )

            else:
                st.caption(
                    "Summary is generated during processing."
                )

            if st.button(
                "Delete",
                key=f"delete-{document['id']}",
                type="secondary",
            ):
                try:
                    api.delete_document(document["id"])
                    st.success(
                        f"Deleted {document['filename']}"
                    )
                    st.rerun()

                except api.ApiError as exc:
                    st.error(str(exc))

    if pending and st.session_state.get("auto_refresh"):
        time.sleep(3)
        st.rerun()


def page_upload() -> None:

    st.subheader("Upload documents")

    st.caption(
        f"Up to {MAX_FILES} files per upload, "
        f"{MAX_FILE_SIZE_MB} MB each. "
        "Processing (chunking, embedding, summarising) runs in the "
        "background once the upload is accepted."
    )

    uploaded = st.file_uploader(
        "Choose documents",
        type=ACCEPTED_EXTENSIONS,
        accept_multiple_files=True,
    )

    if not uploaded:
        return

    oversized = [
        file.name
        for file in uploaded
        if file.size > MAX_FILE_SIZE_MB * 1024 * 1024
    ]

    if oversized:
        st.warning(
            "These exceed the size limit and will be rejected: "
            + ", ".join(oversized)
        )

    if len(uploaded) > MAX_FILES:
        st.warning(
            f"{len(uploaded)} files selected, but the limit is "
            f"{MAX_FILES}."
        )

    if not st.button(
        f"Upload {len(uploaded)} file(s)",
        type="primary",
    ):
        return

    payload = [
        (
            file.name,
            file.getvalue(),
            file.type,
        )
        for file in uploaded
    ]

    with st.spinner("Uploading and starting processing…"):

        try:
            documents = api.upload_documents(payload)

        except api.ApiError as exc:
            st.error(str(exc))
            return

    st.success(
        f"Accepted {len(documents)} document(s). "
        "Track progress on the Library tab."
    )

    for document in documents:
        st.write(
            f"• {document['filename']} — `{document['id']}`"
        )


def page_search(top_k: int) -> None:

    st.subheader("Semantic search")

    st.caption(
        "Raw chunk retrieval with no model involved. Useful for checking "
        "what the answerer is actually being given."
    )

    query = st.text_input(
        "Search query",
        key="search_query",
    )

    if not query:
        return

    with st.spinner("Searching…"):

        try:
            response = api.search(
                query,
                top_k=top_k,
            )

        except api.ApiError as exc:
            st.error(str(exc))
            return

    results = response.get("results") or []

    if not results:
        st.info(
            "Nothing matched. The library may be empty, or the documents "
            "may still be processing."
        )
        return

    st.caption(f"{len(results)} chunk(s), closest first")

    for index, result in enumerate(results, start=1):

        with st.expander(
            f"[{index}] {result['filename']} "
            f"· chunk {result['chunk_index']} "
            f"· distance {result['score']:.4f}",
            expanded=index == 1,
        ):
            st.markdown(
                '<div class="p6-chunk">'
                + html.escape(result["content"])
                + "</div>",
                unsafe_allow_html=True,
            )


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

def main() -> None:

    st.set_page_config(
        page_title="PORT-6",
        page_icon="📄",
        layout="wide",
    )

    st.markdown(
        STYLES,
        unsafe_allow_html=True,
    )

    st.title("📄 PORT-6")
    st.caption(
        "Ask questions in plain English and get answers cited back to "
        "your documents."
    )

    with st.sidebar:

        st.header("Settings")

        if api.health():
            st.success(f"API connected\n\n{api.API_URL}")

        else:
            st.error(
                f"No API at {api.API_URL}\n\n"
                "Start it with:\n\n"
                "`uvicorn port6.main:app --reload`"
            )

        mode = st.radio(
            "RAG mode",
            options=list(MODES),
            format_func=lambda key: MODES[key]["label"],
            help=(
                "Each mode answers the same question with an "
                "increasingly capable retrieval strategy."
            ),
        )

        st.caption(MODES[mode]["help"])

        top_k = st.slider(
            "Chunks to retrieve",
            min_value=1,
            max_value=20,
            value=5,
            help=(
                "How many document chunks are retrieved and offered to "
                "the model as sources."
            ),
        )

        st.checkbox(
            "Auto-refresh library while processing",
            key="auto_refresh",
            value=True,
        )

        if st.button(
            "Clear conversation",
            use_container_width=True,
        ):
            st.session_state["ask_history"] = []
            st.rerun()

    (
        ask_tab,
        compare_tab,
        library_tab,
        upload_tab,
        search_tab,
    ) = st.tabs(
        [
            "Ask",
            "Compare modes",
            "Library",
            "Upload",
            "Search",
        ]
    )

    with ask_tab:
        page_ask(top_k, mode)

    with compare_tab:
        page_compare(top_k)

    with library_tab:
        page_library()

    with upload_tab:
        page_upload()

    with search_tab:
        page_search(top_k)


# Streamlit executes the script with __name__ set to "__main__". Guarding the
# call keeps the module importable for tests without running the whole app.
if __name__ == "__main__":
    main()
