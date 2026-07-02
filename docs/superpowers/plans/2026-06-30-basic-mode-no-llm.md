# Basic Mode: Non-LLM Query Parsing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM in basic search mode with a deterministic, CV-free query parser, and move CV management into a collapsible sidebar.

**Architecture:** A new pure function `parse_query(query) -> SearchFilters` extracts filters via robust regex/lexicons and produces a cleaned `semantic_query`; `routers/search.py` uses it instead of the Groq `extract_filters` and no longer requires a CV. Advanced mode is untouched. The frontend consolidates CV upload/view into the sidebar (removing the standalone page) and makes the sidebar open/close.

**Tech Stack:** Python 3 / FastAPI / pytest (backend); React 18 + TypeScript + Vite + react-router (frontend).

## Global Constraints

- Advanced mode is UNCHANGED — do not touch `backend/backend/search/advanced/*`, `routers/search_advanced.py`, `query_understanding.py`, or `routers/preferences.py`.
- Ingestion is UNCHANGED — LLM extraction of `is_consulting`, `industry`, etc. on ingest stays.
- `SearchFilters` schema and `build_clauses` (`backend/backend/search/filters.py`) do NOT change.
- Basic mode uses NO LLM and NO CV.
- Conservative stripping: ambiguous content-noun keywords (contract/stage/lead/staff/intern/contractor) set the filter but stay in `semantic_query`; only unambiguous control phrases are stripped.
- Git commits: never add a "Co-Authored-By" trailer.
- Backend tests need a live Postgres at `postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test`. Run backend commands from `backend/` via `uv run`.
- Frontend typecheck/build: `npm run build` (runs `tsc && vite build`) from `frontend/`.

---

## File Structure

- Create `backend/backend/search/query_parsing.py` — `parse_query(query: str) -> SearchFilters`.
- Create `backend/tests/search/test_query_parsing.py` — unit tests for the parser.
- Modify `backend/backend/routers/search.py` — use `parse_query`, drop Groq + CV requirement.
- Modify `backend/tests/search/test_search_endpoint.py` — drop Groq mock, assert no-CV works.
- Create `frontend/src/hooks/useSidebarOpen.ts` — localStorage-backed open/close hook.
- Modify `frontend/src/components/Sidebar.tsx` — add CV section, remove CV nav link, add collapse.
- Modify `frontend/src/components/AppLayout.tsx` — wire collapse state + floating toggle.
- Modify `frontend/src/App.tsx` — remove `/cv` route + import.
- Modify `frontend/src/pages/Login.tsx` — always redirect to `/search`.
- Delete `frontend/src/pages/CV.tsx`.

---

## Task 1: Deterministic query parser

**Files:**
- Create: `backend/backend/search/query_parsing.py`
- Test: `backend/tests/search/test_query_parsing.py`

**Interfaces:**
- Consumes: `backend.search.filters.SearchFilters` (existing; `semantic_query: str` required, `max_age_hours: int | None = 720`, all other filter fields default `None`/`False`).
- Produces: `parse_query(query: str) -> SearchFilters`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/search/test_query_parsing.py`:

```python
import pytest
from backend.search.query_parsing import parse_query


def test_plain_query_passthrough():
    f = parse_query("machine learning engineer")
    assert f.semantic_query == "machine learning engineer"
    assert f.seniority is None
    assert f.location_type is None
    assert f.max_age_hours == 720  # default preserved


@pytest.mark.parametrize("query,field,value", [
    ("remote python dev", "location_type", "remote"),
    ("wfh python dev", "location_type", "remote"),
    ("work from home python dev", "location_type", "remote"),
    ("hybrid python dev", "location_type", "hybrid"),
    ("on-site python dev", "location_type", "on-site"),
    ("on site python dev", "location_type", "on-site"),
    ("senior python dev", "seniority", "senior"),
    ("sr. python dev", "seniority", "senior"),
    ("junior python dev", "seniority", "junior"),
    ("jr python dev", "seniority", "junior"),
    ("entry-level python dev", "seniority", "junior"),
    ("mid-level python dev", "seniority", "mid"),
    ("full-time python dev", "employment_type", "full-time"),
    ("part time python dev", "employment_type", "part-time"),
    ("internship python", "employment_type", "internship"),
    ("freelance python dev", "employment_type", "freelance"),
])
def test_enum_filters(query, field, value):
    assert getattr(parse_query(query), field) == value


def test_strict_flag():
    assert parse_query("python dev strictly").strict is True
    assert parse_query("python dev").strict is False


@pytest.mark.parametrize("query,hours", [
    ("python jobs last 3 days", 72),
    ("python jobs past 2 hours", 2),
    ("python jobs last three weeks", 504),
    ("python jobs within 48 hours", 48),
    ("python jobs today", 24),
    ("python jobs yesterday", 48),
    ("python jobs this week", 168),
])
def test_time_window(query, hours):
    assert parse_query(query).max_age_hours == hours


def test_startup_positive_and_negative():
    assert parse_query("python dev at a startup").is_startup is True
    assert parse_query("python dev no startup").is_startup is False
    assert parse_query("python dev").is_startup is None


def test_consulting_positive_and_negative():
    assert parse_query("python consulting role").is_consulting is True
    assert parse_query("python dev without consulting").is_consulting is False


def test_languages():
    assert parse_query("dev fluent in german").languages_required == ["German"]
    assert parse_query("english-speaking dev").languages_required == ["English"]
    assert set(parse_query("dev in english and german").languages_required) == {"English", "German"}


def test_country():
    assert parse_query("python jobs in germany").country == "Germany"
    assert parse_query("python jobs in the united kingdom").country == "United Kingdom"


def test_numeric_thresholds():
    assert parse_query("companies with financial health above 7").min_financial_health_score == 7
    assert parse_query("review score at least 4.5 please").min_review_score == 4.5


def test_multi_filter_and_strip():
    f = parse_query("senior remote python developer at a startup, last 3 days, strictly")
    assert f.seniority == "senior"
    assert f.location_type == "remote"
    assert f.is_startup is True
    assert f.max_age_hours == 72
    assert f.strict is True
    # control tokens are stripped from the content query; incidental filler
    # words ("at a") may remain — we only assert the content survives and the
    # control keywords are gone.
    assert "python developer" in f.semantic_query
    for gone in ("senior", "remote", "startup", "strictly", "last 3 days"):
        assert gone not in f.semantic_query


def test_conservative_strip_keeps_ambiguous_words():
    # 'contract' is an ambiguous content noun -> filter set, word kept
    f = parse_query("contract law positions")
    assert f.employment_type == "contract"
    assert "contract law" in f.semantic_query


def test_word_boundary_no_false_trigger():
    # 'remotely' must NOT trigger location_type=remote
    assert parse_query("delivered work remotely sometimes").location_type is None


def test_empty_after_strip_falls_back_to_raw():
    f = parse_query("remote")
    assert f.semantic_query == "remote"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/search/test_query_parsing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.search.query_parsing'`.

- [ ] **Step 3: Implement the parser**

Create `backend/backend/search/query_parsing.py`:

```python
import re

from backend.search.filters import SearchFilters

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_UNIT_HOURS = {"hour": 1, "day": 24, "week": 168}

# (regex, field, value, strip?) — first match per field wins.
_ENUM_RULES = [
    (r"\bwork from home\b", "location_type", "remote", True),
    (r"\bwfh\b", "location_type", "remote", True),
    (r"\bremote\b", "location_type", "remote", True),
    (r"\bhybrid\b", "location_type", "hybrid", True),
    (r"\bon[- ]?site\b", "location_type", "on-site", True),
    (r"\bfull[- ]?time\b", "employment_type", "full-time", True),
    (r"\bpart[- ]?time\b", "employment_type", "part-time", True),
    (r"\binternships?\b", "employment_type", "internship", True),
    (r"\binterns?\b", "employment_type", "internship", False),
    (r"\bfreelance(?:r)?\b", "employment_type", "freelance", True),
    (r"\bcontractor\b", "employment_type", "contract", False),
    (r"\bcontract\b", "employment_type", "contract", False),
    (r"\bstage\b", "employment_type", "stage", False),
    (r"\bentry[- ]?level\b", "seniority", "junior", True),
    (r"\bjunior\b", "seniority", "junior", True),
    (r"\bjr\.?\b", "seniority", "junior", True),
    (r"\bmid[- ]?level\b", "seniority", "mid", True),
    (r"\bsenior\b", "seniority", "senior", True),
    (r"\bsr\.?\b", "seniority", "senior", True),
    (r"\blead\b", "seniority", "lead", False),
    (r"\bprincipal\b", "seniority", "principal", False),
    (r"\bstaff\b", "seniority", "staff", False),
    (r"\bdirector\b", "seniority", "director", False),
]

_STRICT_RULES = [
    (r"\bstrictly\b", True),
    (r"\bexactly\b", True),
    (r"\bno exceptions\b", True),
]

_LANGS = [
    "english", "german", "french", "spanish", "italian", "dutch",
    "portuguese", "chinese", "mandarin", "japanese", "arabic",
    "russian", "polish", "swedish",
]
_LANG_ALT = "|".join(_LANGS)

# canonical name keyed by the lowercase form matched
_COUNTRIES = {
    "united kingdom": "United Kingdom", "united states": "United States",
    "germany": "Germany", "france": "France", "spain": "Spain",
    "italy": "Italy", "netherlands": "Netherlands", "poland": "Poland",
    "portugal": "Portugal", "ireland": "Ireland", "switzerland": "Switzerland",
    "austria": "Austria", "belgium": "Belgium", "sweden": "Sweden",
    "canada": "Canada",
}
# longest first so multi-word countries win
_COUNTRY_KEYS = sorted(_COUNTRIES, key=len, reverse=True)

_NEG = r"(?:no|not|without|non[- ]?|excluding)\s+"


def parse_query(query: str) -> SearchFilters:
    text = query.lower()
    semantic = text
    fields: dict = {}

    def strip(pattern: str) -> None:
        nonlocal semantic
        semantic = re.sub(pattern, " ", semantic)

    # --- negatable booleans ---
    for field, kw in (("is_startup", r"start[- ]?ups?"), ("is_consulting", r"consult(?:ing|ancy)")):
        if re.search(_NEG + kw + r"\b", text):
            fields[field] = False
            strip(_NEG + kw + r"\b")
        elif re.search(r"\b" + kw + r"\b", text):
            fields[field] = True
            strip(r"\b" + kw + r"\b")

    # --- time window ---
    num = r"(\d+|" + "|".join(_NUM_WORDS) + r")"
    m = re.search(r"\b(?:last|past|previous|within|in the last)\s+" + num + r"\s+(hour|day|week)s?\b", text)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
        fields["max_age_hours"] = n * _UNIT_HOURS[m.group(2)]
        strip(m.re.pattern)
    elif re.search(r"\btoday\b", text):
        fields["max_age_hours"] = 24
        strip(r"\btoday\b")
    elif re.search(r"\byesterday\b", text):
        fields["max_age_hours"] = 48
        strip(r"\byesterday\b")
    elif re.search(r"\bthis week\b", text):
        fields["max_age_hours"] = 168
        strip(r"\bthis week\b")

    # --- numeric thresholds (explicit phrasing only) ---
    _OP = r"(?:>=|≥|above|over|at least|min(?:imum)?|greater than|more than)\s*"
    mf = re.search(r"financial(?: health)?(?: score)?\s*" + _OP + r"(\d+)", text)
    if mf:
        fields["min_financial_health_score"] = int(mf.group(1))
        strip(mf.re.pattern)
    mr = re.search(r"review(?: score)?\s*" + _OP + r"(\d+(?:\.\d+)?)", text)
    if mr:
        fields["min_review_score"] = float(mr.group(1))
        strip(mr.re.pattern)

    # --- languages (trigger-based) ---
    langs: list[str] = []
    for lang in re.findall(r"\b(" + _LANG_ALT + r")[- ]speaking\b", text):
        langs.append(lang)
    for chain in re.findall(
        r"\b(?:in|fluent in|speaks?|speaking|knowledge of)\s+((?:" + _LANG_ALT +
        r")(?:\s*(?:,|and|&)\s*(?:" + _LANG_ALT + r"))*)\b", text):
        langs.extend(re.findall(_LANG_ALT, chain))
    if langs:
        seen = []
        for lang in langs:
            title = lang.capitalize()
            if title not in seen:
                seen.append(title)
        fields["languages_required"] = seen
        strip(r"\b(" + _LANG_ALT + r")[- ]speaking\b")
        strip(r"\b(?:in|fluent in|speaks?|speaking|knowledge of)\s+((?:" + _LANG_ALT +
              r")(?:\s*(?:,|and|&)\s*(?:" + _LANG_ALT + r"))*)\b")

    # --- country ---
    for key in _COUNTRY_KEYS:
        if re.search(r"\b" + re.escape(key) + r"\b", text):
            fields["country"] = _COUNTRIES[key]
            strip(r"\b(?:in\s+)?(?:the\s+)?" + re.escape(key) + r"\b")
            break

    # --- enum filters (first per field wins) ---
    for pattern, field, value, do_strip in _ENUM_RULES:
        if field in fields:
            continue
        if re.search(pattern, text):
            fields[field] = value
            if do_strip:
                strip(pattern)

    # --- strict flag ---
    for pattern, value in _STRICT_RULES:
        if re.search(pattern, text):
            fields["strict"] = value
            strip(pattern)

    semantic = re.sub(r"\s{2,}", " ", semantic).strip(" ,.-")
    if not semantic:
        semantic = query.strip()

    return SearchFilters(semantic_query=semantic, **fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/search/test_query_parsing.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/query_parsing.py backend/tests/search/test_query_parsing.py
git commit -m "feat(search): deterministic non-LLM query parser for basic mode"
```

---

## Task 2: Wire parser into basic search endpoint

**Files:**
- Modify: `backend/backend/routers/search.py`
- Test: `backend/tests/search/test_search_endpoint.py`

**Interfaces:**
- Consumes: `parse_query(query: str) -> SearchFilters` (Task 1).
- Produces: `POST /jobs/search` that needs no Groq client and no CV.

- [ ] **Step 1: Update the endpoint tests (failing)**

In `backend/tests/search/test_search_endpoint.py`:

Delete the `_mock_groq` helper (lines defining it) and the `get_groq_client` import.
Replace the import line:

```python
from backend.search.query_understanding import get_groq_client
```
with nothing (remove it).

In the `search_client` fixture, remove this line:

```python
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
```

Replace the entire `test_search_returns_400_when_no_cv` function with:

```python
async def test_search_works_without_cv(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    user_id = uuid.uuid4()
    async with factory() as session:
        user = User(id=user_id, username="testuser_nocv", password_hash="x")
        session.add(user)
        await session.commit()

    mock_user = User(id=user_id, username="testuser_nocv", password_hash="x")

    async def override_session():
        async with factory() as session:
            yield session

    mock_biencoder = MagicMock()
    encode_result = MagicMock()
    encode_result.tolist.return_value = [0.0] * 384
    mock_biencoder.encode.return_value = encode_result
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.9]
    mock_os = AsyncMock()
    mock_os.search.return_value = {"hits": {"hits": []}}

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: mock_biencoder
    app.dependency_overrides[get_reranker] = lambda: mock_reranker
    app.dependency_overrides[get_opensearch] = lambda: mock_os
    app.dependency_overrides[get_current_user] = lambda: mock_user

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/jobs/search", json={"query": "ml engineer"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []
```

Remove the now-unused `import json` if nothing else uses it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/search/test_search_endpoint.py -q`
Expected: FAIL — `test_search_works_without_cv` returns 400 (CV still required) and/or fixture errors on the removed `get_groq_client` override.

- [ ] **Step 3: Update the router**

Edit `backend/backend/routers/search.py`. Replace the imports block (lines 1-23) so it no longer imports Groq/query_understanding/ApplicantProfile and adds `parse_query`:

```python
import logging
import time
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel

from backend.database import get_session
from backend.models import Job, User
from backend.schemas import JobSearchResponse
from backend.search.filters import SearchFilters
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_parsing import parse_query
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.opensearch_client import get_opensearch
from backend.auth.dependencies import get_current_user
```

Replace the function signature + CV check + filter extraction (current lines 33-53) with:

```python
@router.post("/search", response_model=list[JobSearchResponse])
async def search_jobs(
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
) -> list[JobSearchResponse]:
    t0 = time.perf_counter()

    filters: SearchFilters = parse_query(body.query)
    t1 = time.perf_counter()
```

Update the timing log lines (current lines 65 and 74) to label the first phase `parse` instead of `query_understanding` (replace `query_understanding=%.3fs` with `parse=%.3fs` in both log strings). Leave the rest of the function unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/search/test_search_endpoint.py -q`
Expected: PASS (3 tests: ranked jobs, empty list, works without CV).

- [ ] **Step 5: Run the full search test suite**

Run: `cd backend && uv run pytest tests/search -q`
Expected: PASS (advanced + filters + parser + endpoint untouched-and-passing).

- [ ] **Step 6: Commit**

```bash
git add backend/backend/routers/search.py backend/tests/search/test_search_endpoint.py
git commit -m "feat(search): basic mode uses deterministic parser, no CV required"
```

---

## Task 3: CV management in the sidebar + remove standalone page

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Login.tsx`
- Delete: `frontend/src/pages/CV.tsx`

**Interfaces:**
- Consumes: existing `getCV()`/`uploadCV(file)` from `frontend/src/api/cv.ts`.

- [ ] **Step 1: Add a CV section to the sidebar**

In `frontend/src/components/Sidebar.tsx`, add imports near the top:

```typescript
import { useRef } from 'react'
import { getCV, uploadCV } from '../api/cv'
```

(Merge `useRef` into the existing `import { useEffect, useState } from 'react'` line → `import { useEffect, useRef, useState } from 'react'`.)

Add state inside the component (next to the other `useState` calls):

```typescript
  const [cvChars, setCvChars] = useState<number | null>(null)
  const [cvText, setCvText] = useState('')
  const [showCv, setShowCv] = useState(false)
  const [cvError, setCvError] = useState('')
  const [cvBusy, setCvBusy] = useState(false)
  const cvInputRef = useRef<HTMLInputElement>(null)
```

Extend the existing mount effect to also load the CV:

```typescript
  useEffect(() => {
    me().then(setUser).catch(() => {})
    getPreferenceMemory().then(p => setMemory(p.memory_text || '')).catch(() => {})
    getCV().then(({ cv_text }) => {
      setCvText(cv_text || '')
      setCvChars(cv_text ? cv_text.length : null)
    }).catch(() => {})
  }, [])
```

Add a handler:

```typescript
  const handleCvFile = async (file: File) => {
    setCvError('')
    setCvBusy(true)
    try {
      const res = await uploadCV(file)
      setCvChars(res.char_count)
      const { cv_text } = await getCV()
      setCvText(cv_text || '')
    } catch (err: any) {
      setCvError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setCvBusy(false)
    }
  }
```

Remove the CV nav link — change:

```typescript
        {navLink('/search', 'Search')}
        {navLink('/cv', 'CV')}
```
to:

```typescript
        {navLink('/search', 'Search')}
```

Add the CV section markup just above the "Preferences (learned)" block:

```tsx
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
        <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>
          CV {cvChars != null ? `(${cvChars.toLocaleString()} chars)` : '(none)'}
        </div>
        <button onClick={() => cvInputRef.current?.click()} disabled={cvBusy}
                style={{ padding: '0.35rem', borderRadius: 6, cursor: 'pointer' }}>
          {cvBusy ? 'Uploading...' : cvChars != null ? 'Replace CV' : 'Upload CV'}
        </button>
        <input ref={cvInputRef} type="file" accept=".pdf,.docx,.txt" style={{ display: 'none' }}
               onChange={e => { const f = e.target.files?.[0]; if (f) handleCvFile(f) }} />
        {cvChars != null && (
          <button onClick={() => setShowCv(s => !s)}
                  style={{ padding: '0.25rem', borderRadius: 6, cursor: 'pointer', fontSize: '0.75rem', background: 'transparent', color: '#aaa', border: '1px solid #2a2a2a' }}>
            {showCv ? 'Hide CV' : 'View CV'}
          </button>
        )}
        {showCv && (
          <textarea value={cvText} readOnly rows={8}
                    style={{ resize: 'vertical', fontSize: '0.75rem', background: '#141414', color: '#ccc', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.4rem' }} />
        )}
        {cvError && <span style={{ fontSize: '0.75rem', color: '#f87171' }}>{cvError}</span>}
      </div>
```

- [ ] **Step 2: Remove the `/cv` route**

In `frontend/src/App.tsx`, delete the import line `import CV from './pages/CV'` and delete the route line:

```tsx
      <Route path="/cv" element={<PrivateRoute><AppLayout><CV /></AppLayout></PrivateRoute>} />
```

- [ ] **Step 3: Always redirect to /search after login**

In `frontend/src/pages/Login.tsx`, change line 22:

```typescript
      navigate(user.has_cv ? '/search' : '/cv')
```
to:

```typescript
      navigate('/search')
```

- [ ] **Step 4: Delete the standalone CV page**

```bash
rm frontend/src/pages/CV.tsx
```

- [ ] **Step 5: Typecheck / build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors (no unresolved `./pages/CV` import, no unused `CV` symbol).

- [ ] **Step 6: Manual verification**

Run `cd frontend && npm run dev`. Log in; confirm: you land on `/search`; the sidebar shows a CV section; "Upload CV" stores a file and the char count appears; "View CV" toggles the text; basic search works with no CV uploaded; there is no `/cv` nav link.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Sidebar.tsx frontend/src/App.tsx frontend/src/pages/Login.tsx
git rm frontend/src/pages/CV.tsx
git commit -m "feat(frontend): manage CV in sidebar, remove standalone CV page"
```

---

## Task 4: Collapsible sidebar

**Files:**
- Create: `frontend/src/hooks/useSidebarOpen.ts`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`

**Interfaces:**
- Produces: `useSidebarOpen() -> { open: boolean, toggle: () => void }`.
- `Sidebar` gains an `onToggle: () => void` prop (renders the in-panel collapse button).

- [ ] **Step 1: Create the open/close hook**

Create `frontend/src/hooks/useSidebarOpen.ts` (mirrors `useSearchMode`):

```typescript
import { useSyncExternalStore } from 'react'

const KEY = 'sidebar_open'
const listeners = new Set<() => void>()

function getSnapshot(): boolean {
  return localStorage.getItem(KEY) !== 'false' // default open
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  window.addEventListener('storage', cb)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('storage', cb)
  }
}

function setOpen(v: boolean) {
  localStorage.setItem(KEY, String(v))
  listeners.forEach((l) => l())
}

export function useSidebarOpen() {
  const open = useSyncExternalStore(subscribe, getSnapshot)
  return { open, toggle: () => setOpen(!open) }
}
```

- [ ] **Step 2: Add an in-panel collapse button to the sidebar**

In `frontend/src/components/Sidebar.tsx`, change the component signature to accept the toggle:

```typescript
export default function Sidebar({ onToggle }: { onToggle: () => void }) {
```

Add a header row with a collapse button as the first child inside the `<aside>` (above the username `<div>`):

```tsx
      <button onClick={onToggle} aria-label="Collapse sidebar"
              style={{ alignSelf: 'flex-end', background: 'transparent', color: '#aaa', border: 'none', cursor: 'pointer', fontSize: '1.1rem' }}>
        ☰
      </button>
```

- [ ] **Step 3: Wire collapse state + floating toggle in AppLayout**

Replace `frontend/src/components/AppLayout.tsx` with:

```tsx
import Sidebar from './Sidebar'
import { useSidebarOpen } from '../hooks/useSidebarOpen'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { open, toggle } = useSidebarOpen()
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {open ? (
        <Sidebar onToggle={toggle} />
      ) : (
        <button onClick={toggle} aria-label="Open sidebar"
                style={{ position: 'fixed', top: 12, left: 12, zIndex: 10, background: '#1f1f1f', color: '#fff', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.35rem 0.6rem', cursor: 'pointer' }}>
          ☰
        </button>
      )}
      <main style={{ flex: 1, minWidth: 0 }}>{children}</main>
    </div>
  )
}
```

- [ ] **Step 4: Typecheck / build**

Run: `cd frontend && npm run build`
Expected: build succeeds; `Sidebar` is called with `onToggle` in `AppLayout` (no missing-prop TS error).

- [ ] **Step 5: Manual verification**

Run `cd frontend && npm run dev`. Confirm: the sidebar shows a ☰ collapse button; clicking it hides the panel and a floating ☰ appears top-left; clicking that reopens it; the open/closed state survives a page reload (localStorage `sidebar_open`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useSidebarOpen.ts frontend/src/components/Sidebar.tsx frontend/src/components/AppLayout.tsx
git commit -m "feat(frontend): collapsible open/close sidebar"
```

---

## Notes / known limitations

- Country and language lexicons are intentionally curated subsets; extend as needed. Matched `country` is stored title-cased and assumes the index stores the same form.
- Numeric thresholds only fire on explicit phrasing (e.g. "financial health above 7"); they stay `null` otherwise — by design.
- Frontend has no automated test suite in this repo; Tasks 3-4 are verified via `npm run build` + manual steps.
