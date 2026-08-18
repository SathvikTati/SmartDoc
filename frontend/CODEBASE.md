# Frontend Codebase Map

What each module is and what it does. The backend has its own pair:
[../CODEBASE.md](../CODEBASE.md) and [../WORKFLOW.md](../WORKFLOW.md).

Plain JavaScript, not TypeScript. Vite, React Router, Tailwind, Axios,
Lucide icons. No component library — the primitives in `components/ui/`
are the whole design system.

```
frontend/src/
├── App.jsx                 routes, and the provider stack around them
├── main.jsx                mount
├── index.css               design tokens, light and dark
├── pages/                  one file per route
├── components/
│   ├── layout/             the shell: sidebar, header, page body
│   ├── rag/                answers, citations, evidence, traces
│   ├── files/              the explorer: views, preview, upload
│   ├── settings/           the defaults dialog
│   └── ui/                 the primitives everything else is built from
├── state/                  three contexts
├── lib/                    the API client and formatting
└── test/                   render helper and fixtures
```

---

## Routes

| Route | Page | Lines | What it is |
|---|---|---:|---|
| `/ask` | [`AskPage.jsx`](src/pages/AskPage.jsx) | 579 | The home route. A conversation of turns, each keeping its own answer, citations and trace. Composer with mode, Top-K and document scope. |
| `/files` | [`FilesPage.jsx`](src/pages/FilesPage.jsx) | 663 | The library as a file explorer: two views, sorting, multi-select, right-click, keyboard delete, a live status bar. |
| `/files/:id` | [`DocumentDetailPage.jsx`](src/pages/DocumentDetailPage.jsx) | 364 | One document: summary, section tree, every chunk with its page and offsets. |
| `/pipelines` | [`PipelinesPage.jsx`](src/pages/PipelinesPage.jsx) | 624 | Build two to four pipelines and run one question through all of them. Metrics table, then answers side by side. |
| `/compare` | [`ComparePage.jsx`](src/pages/ComparePage.jsx) | 408 | The coarse three-family comparison. |
| `/search` | [`SearchPage.jsx`](src/pages/SearchPage.jsx) | 318 | Raw retrieval with no model, for asking "was the right chunk even found?" |
| `/history` | [`HistoryPage.jsx`](src/pages/HistoryPage.jsx) | 288 | Every run, grouped by conversation. |
| `*` | [`NotFoundPage.jsx`](src/pages/NotFoundPage.jsx) | 66 | A real 404, outside the shell — a missing page has no breadcrumb trail. |

---

## State

Three contexts, each owning one thing. They wrap the router in
[`App.jsx`](src/App.jsx) so every route sees the same data.

| File | Lines | Owns |
|---|---:|---|
| [`state/SettingsContext.jsx`](src/state/SettingsContext.jsx) | 115 | What a pipeline can be built from (retrievers, tools, presets) and the chat defaults (`defaults.mode`, `defaults.top_k`). Stored server-side, not in this browser — a default in `localStorage` would differ per machine and would not apply to an API call. |
| [`state/DocumentsContext.jsx`](src/state/DocumentsContext.jsx) | 118 | The library, and whether the API is reachable. Polls while anything is still ingesting and stops when nothing is. |
| [`state/InvestigationsContext.jsx`](src/state/InvestigationsContext.jsx) | 169 | Conversations. A chat is the unit a follow-up resolves against, so the UI works in chats — but it is not a chat transcript: nothing collapses into a running stream. |

---

## Components

### Layout

| File | Lines | What it does |
|---|---:|---|
| [`layout/AppLayout.jsx`](src/components/layout/AppLayout.jsx) | 47 | The shell, and `PageBody` — the scrolling region with the standard gutter. Files opts out; an explorer manages its own panes. |
| [`layout/Sidebar.jsx`](src/components/layout/Sidebar.jsx) | 151 | Navigation, recent conversations (capped at eight), API status. |
| [`layout/Header.jsx`](src/components/layout/Header.jsx) | 47 | Breadcrumbs, page actions, and the Defaults button. Defaults live in the shell because they apply to a new chat regardless of which page started it. |
| [`layout/Breadcrumbs.jsx`](src/components/layout/Breadcrumbs.jsx) | — | Location, nothing more. |

### Answers

| File | Lines | What it does |
|---|---:|---|
| [`rag/InvestigationView.jsx`](src/components/rag/InvestigationView.jsx) | 324 | One answered question: the question, the answer, sources, retrieved evidence, the trace. Renders a greeting compactly, with no evidence panels — nothing was retrieved, and four empty ones would imply otherwise. |
| [`rag/AnswerBody.jsx`](src/components/rag/AnswerBody.jsx) | 233 | Renders the answer, turning `[n]` into a clickable pill. Handles the markdown a local model emits — bold, lists, inline code — without a markdown library, because the input is one paragraph of model output and not a document. |
| [`rag/ChunkCard.jsx`](src/components/rag/ChunkCard.jsx) | 192 | One retrieved chunk: provenance, which retriever found it, ranks, scores. A web chunk links out; a calculation links nowhere and names the sources its figures came from. |
| [`rag/RetrievalTrace.jsx`](src/components/rag/RetrievalTrace.jsx) | 314 | What retrieval actually did — stages, tools, ranks, validation. |
| [`rag/QueryControls.jsx`](src/components/rag/QueryControls.jsx) | 78 | Mode and Top-K for a chat. Three modes only — composing a pipeline is a retrieval question, and `/pipelines` is where it gets answered. |
| [`rag/CompositionBuilder.jsx`](src/components/rag/CompositionBuilder.jsx) | 210 | One pipeline, composed: retriever chips, an agent switch, and — only once the agent is on — the tools it may reach for. Tools appear when they start mattering rather than sitting greyed out. |

### Files

| File | Lines | What it does |
|---|---:|---|
| [`files/FileViews.jsx`](src/components/files/FileViews.jsx) | 193 | Details and icons views, sortable, selectable. |
| [`files/PreviewPane.jsx`](src/components/files/PreviewPane.jsx) | 255 | The right-hand pane for a single selection. |
| [`files/UploadDialog.jsx`](src/components/files/UploadDialog.jsx) | 396 | Drag and drop, per-file validation before the request, live ingestion status, and the note about deleting a version you are replacing. |

### Settings

| File | Lines | What it does |
|---|---:|---|
| [`settings/DefaultsDialog.jsx`](src/components/settings/DefaultsDialog.jsx) | 220 | Mode and Top-K for new chats. Two fields on purpose: everything else configurable belongs to whoever is tuning the system, not to whoever is asking it questions. |

### Primitives

`components/ui/` — [`Button`](src/components/ui/Button.jsx),
[`Badge`](src/components/ui/Badge.jsx),
[`Panel`](src/components/ui/Panel.jsx) and `SectionHeading`,
[`Field`](src/components/ui/Field.jsx) (`Input`, `Textarea`, `Select`,
`SegmentedControl`, `Label`), [`Pill`](src/components/ui/Pill.jsx),
[`Disclosure`](src/components/ui/Disclosure.jsx),
[`ContextMenu`](src/components/ui/ContextMenu.jsx),
[`States`](src/components/ui/States.jsx) (empty, error, skeleton).

`Select` takes either a flat `options` array or children — children exist
because a flat list cannot express `<optgroup>`.

---

## Library

| File | Lines | What it does |
|---|---:|---|
| [`lib/api.js`](src/lib/api.js) | 279 | Every call, one Axios instance. Long timeouts on `/ask` — a local model is slow — scaled by how many pipelines a comparison asked for. Turns a FastAPI error body into a readable message. |
| [`lib/format.js`](src/lib/format.js) | 105 | `cn`, bytes, counts, relative time, latency, truncation. |
| [`lib/constants.js`](src/lib/constants.js) | — | Accepted extensions, file limits. |

---

## Tests

`npm test` — vitest, jsdom, Testing Library. 19 tests across three files.

| File | Covers |
|---|---|
| [`pages/pages.smoke.test.jsx`](src/pages/pages.smoke.test.jsx) | Every page renders; the composer shows the configured default |
| [`pages/PipelinesPage.test.jsx`](src/pages/PipelinesPage.test.jsx) | Two builders by default, every retriever offered, the tool picker stays hidden until an agent is added, presets appear, a load failure surfaces |
| [`components/settings/DefaultsDialog.test.jsx`](src/components/settings/DefaultsDialog.test.jsx) | Three modes and no more, the saved default is preselected, save is disabled until something changes |
| [`test/render.jsx`](src/test/render.jsx) | The helper: renders inside the real provider stack, with API fixtures |

They exist because **the build does not check rendering**. A page can
compile cleanly and still throw on first paint — a component handed
children where it expected an `options` array does exactly that, and
shipped twice before these were added.

---

## Where to change things

| Goal | File |
|---|---|
| Add a route | `App.jsx` + a page, and `layout/Sidebar.jsx` `NAV` |
| Add an API call | `lib/api.js` |
| Change what a new chat defaults to | the header dialog, or `PUT /settings/defaults.mode` |
| Change the modes offered in a chat | `rag/QueryControls.jsx` `MODE_OPTIONS` |
| Change how a pipeline is composed | `rag/CompositionBuilder.jsx` |
| Add a retriever or tool to the builder | nothing here — add it in the backend and it appears |
| Change a colour | `index.css` tokens. Adding a *key* also needs `tailwind.config.js` and a dev-server restart |
| Change how an answer renders | `rag/AnswerBody.jsx` |
| Change how a chunk renders | `rag/ChunkCard.jsx` |
