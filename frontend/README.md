# PORT-6 — React frontend

The primary user-facing interface for PORT-6. Plain JavaScript (no
TypeScript), React 19, Vite, Tailwind, React Router. Talks to the FastAPI
service over HTTP only; it holds no database or vector-store connection of
its own.

The Streamlit app at [`src/port6/frontend/`](../src/port6/frontend/) is still
present and still works — it stays as the internal debugging surface.

```bash
# terminal 1 — the API
uv run uvicorn port6.main:app --reload

# terminal 2 — the UI
cd frontend
npm install
npm run dev          # http://localhost:5173  → redirects to /ask
```

`npm run dev` proxies `/api/*` to `http://localhost:8000`, so the browser
only ever sees one origin. Point it elsewhere with `PORT6_API_URL`.

For a production build the two are served separately, so calls go straight
to the API and CORS applies:

```bash
VITE_API_URL=https://port6.internal npm run build
npm run preview
```

The API's allowlist lives in `PORT6_CORS_ORIGINS` (see
[`main.py`](../src/port6/main.py)) and defaults to the Vite dev and preview
ports.

---

## Routes

| Route | Purpose |
|---|---|
| `/` | Redirects to `/ask` — the home page |
| `/ask` | Cited answers. Each question is its own investigation, not a chat turn |
| `/files` | The document library — every file in one flat list |
| `/files/:documentId` | One document — file facts, summary, chunk and page counts, heading tree |
| `/search` | Raw chunk retrieval with no model in the loop |
| `/compare` | One question through all three modes, side by side |
| `*` | A real 404 page, reached through the router rather than a reload |

---

## The file explorer

`/files` behaves like a desktop file manager rather than a document list:

- **One flat list** of every document, with a **status bar** at the bottom
- **Details** and **Icons** views, toggled and remembered per browser
- Click selects, **Cmd/Ctrl-click** toggles, **Shift-click** extends a range,
  **double-click** opens
- **Right-click** for a context menu, on rows and on empty space
- **Ctrl/Cmd+A** select all, **Delete** removes, **Esc** clears the selection
- Sort by name, type, size, status or date; filter by status and type;
  search by filename

**There are no folders.** PORT-6 keeps documents flat in Postgres — there is
no folder column, and nothing classifies a document beyond its filename. An
earlier version grouped files into derived folders by department and type;
those were invented, so they are gone. What you get is a single open
directory, which is what the library actually is.

---

## Structure

```
src/
  lib/
    api.js         typed-by-convention client; the only place that knows HTTP
    constants.js   values copied from the backend (statuses, limits, modes)
    format.js      bytes, dates, latencies, class-name join
  state/
    DocumentsContext.jsx       library + ingestion-status polling
    InvestigationsContext.jsx  the session's questions
  components/
    ui/            Button, Badge, Panel, Field, Disclosure, ContextMenu, States
    layout/        AppLayout, Sidebar, Header, Breadcrumbs
    files/         FileViews (details + icons), UploadDialog
    rag/           AnswerBody, ChunkCard, RetrievalTrace, InvestigationView
  pages/           one file per route
```

---

## Three things worth knowing

**Ingestion status is polled, not streamed.** `DocumentsContext` refreshes
every 1.5s while any document is `UPLOADED` or `PROCESSING`, and every 20s
otherwise. There is no websocket; the API does not offer one.

**The upload dialog does not invent progress.** The five gates it ticks off
are the ones the API runs *before* it responds, so a 200 means all five
genuinely passed. The background stages are reported by the API as one
`PROCESSING` state, so they advance as a group — showing them lighting up
one by one would be a fiction.

**A file is just a file.** Documents carry a filename, a size, a status and
a generated summary — nothing infers a title, a type, a department or a
version. Citations therefore read *hr_policy.md, Section 1.1 Annual Leave*,
with the section path coming from the document's own headings.
