# Prism Phase 1 Frontend Redesign Design

Date: 2026-06-13

## Goal

Redesign the Phase 1 Prism frontend around the existing product surface: the main layout, chat page, and knowledge page. The redesign should borrow Comet's mature application structure while giving Prism its own "Prism Lab" identity: a dark navigation shell, blue/cyan/violet highlights, and clearer evidence trails for RAG answers.

This is a frontend-only redesign with small UX improvements. It must not introduce new backend APIs, Ant Design, or Comet modules that Prism does not currently support.

## Decisions

- Scope: Balanced Core. Upgrade `MainLayout`, `ChatPage`, and `KnowledgePage` together.
- Visual direction: Prism Lab. Keep Comet's mature product feel, but add Prism-specific spectrum and retrieval cues.
- UI stack: keep Tailwind CSS and `lucide-react`; do not add Ant Design in Phase 1.
- Behavior scope: frontend visual and interaction improvements only. Existing backend contracts remain unchanged.
- API scope: no backend changes, no new endpoints, no mock backend features.

## Information Architecture

The app remains intentionally small for Phase 1.

- Main layout: product shell with a dark Prism Lab sidebar and a light content area.
- Navigation: only "Chat" and "Knowledge" routes are shown, because they are the only implemented Prism workflows.
- Chat page: the primary work area for RAG conversations.
- Knowledge page: the lightweight workbench for uploading, importing, writing, and reviewing knowledge items.

Comet modules such as login, home dashboard, global search, settings, multi-knowledge-base management, memory, graph, images, music, and agent configuration are out of scope.

## Visual System

Use the following tokens as the basis for CSS/Tailwind classes:

- Ink: `#111827` for the sidebar and brand base.
- Prism Blue: `#155EEF` for primary actions, active navigation, and user messages.
- Ray Cyan: `#22D3EE` for streaming states, citation chips, and retrieval accents.
- Signal Violet: `#8B5CF6` for restrained brand spectrum highlights.
- Surface: `#F7F9FC` for the main page background.
- Line: `#E6EAF2` for borders and dividers.

Typography remains system-first for Chinese product UI: `PingFang SC`, `Microsoft YaHei`, system UI, and sans-serif fallbacks. Markdown answers should use a more readable rhythm than the current UI, roughly `16px` font size and `1.75` line height.

Component styling:

- Sidebar: dark background, compact nav, active route with blue/cyan highlight.
- Main content: light surface, restrained shadows, stable spacing, and `8-12px` radii.
- Buttons: lucide icons for actions, blue primary buttons, white secondary buttons with subtle borders.
- Cards: used for knowledge items and focused tool surfaces only.
- Citation chips: small blue/cyan evidence markers attached to assistant answers.
- Loading, empty, and error states: plain Chinese copy that tells the user what is happening and what to do next.

## Main Layout

`frontend/src/layouts/MainLayout.tsx` should become the shared application frame.

Expected behavior:

- Fixed full-height shell.
- Dark left sidebar on desktop.
- Responsive behavior for smaller screens, using a compact header or collapsible nav pattern without introducing new dependencies.
- Brand area showing "Prism" with a spectrum-style mark built from CSS/lucide primitives.
- Navigation items for Chat and Knowledge only.
- Content area with consistent page padding and no nested page cards.

The layout should feel closer to Comet's stable application shell, but remain lighter than Comet because Prism Phase 1 has fewer modules.

## Chat Page

`frontend/src/pages/ChatPage.tsx` is the core interaction surface.

Required UX:

- Empty state with Prism positioning, suggested starter prompts, and a clear link/action to the knowledge page.
- User messages rendered as right-aligned blue bubbles.
- Assistant messages rendered as left-aligned white reading blocks with improved Markdown styling.
- Streaming assistant messages show a clear state such as "正在检索知识库..." or "正在生成回答..." instead of generic fallback text.
- Existing NDJSON/SSE-style streaming behavior remains unchanged.
- Input area becomes a bottom input card inspired by Comet: stable height, clear send button, disabled state while sending, Enter to send.
- A "clear conversation" action resets the local Zustand message store.
- Request failures render a clear inline error block in the assistant message.

Citation behavior:

- The current backend only provides `chunk_id`, `item_id`, and `score`.
- After an assistant answer finishes, show source chips such as "来源 1", "来源 2".
- Clicking or toggling a source area reveals the available fields: chunk id, item id, and score.
- Do not pretend titles, snippets, or document names exist until the API provides them.

## Knowledge Page

`frontend/src/pages/KnowledgePage.tsx` becomes a lightweight knowledge workbench.

Required UX:

- Header with page title, item count, and primary actions: upload file and create note.
- URL import remains available as a dedicated tool row.
- Create-note form remains inline/expandable, with clearer labels and actions: save note and cancel.
- Knowledge items render in a responsive card grid.
- Cards should show the available fields: title, summary, source type, tags, status, and created date where useful.
- Loading state, empty state, and error state should be visible and specific.
- Delete remains a lightweight confirmation flow, without adding modal dependencies.

The page stays a single knowledge-item list. Multi-knowledge-base management from Comet is out of scope for Phase 1.

## Implementation Boundaries

Do not:

- Add Ant Design.
- Add new backend APIs.
- Add authentication, settings, dashboard, search, memory, graph, image, music, or agent pages.
- Introduce external fonts or network-dependent assets.
- Change engine or backend behavior.
- Refactor unrelated modules.

Allowed:

- Add small frontend-only helper components if they reduce duplication.
- Add CSS classes/tokens in `frontend/src/index.css`.
- Add local UI state for expanding sources or toggling create-note forms.
- Improve copy and error messages.

## Validation

Required verification:

- `pnpm.cmd build` from `frontend`.
- Manual visual check at desktop and mobile widths for layout, chat input, message bubbles, source chips, and knowledge card grid.

Recommended regression:

- `python -m pytest backend engine`

Acceptance criteria:

- Chat and knowledge routes remain reachable.
- Existing streaming chat behavior still works.
- Existing knowledge list, file upload trigger, URL import, note creation, and delete flows remain wired to current API functions.
- Empty, loading, sending, error, and source-display states are all visibly handled.
- The UI reads as Prism Lab rather than a direct Comet copy or a generic Tailwind scaffold.
