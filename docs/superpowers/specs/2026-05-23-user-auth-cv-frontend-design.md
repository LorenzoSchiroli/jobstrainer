# User Auth, CV Upload & React Frontend

**Date:** 2026-05-23  
**Status:** Approved

## Overview

Add user authentication (username + password + JWT), CV upload and storage, update the search endpoint to use the saved CV, and build a simple React frontend. Everything lives in the same FastAPI backend and Postgres database; the frontend is a separate Vite + React service.

---

## Backend

### New `users` Table

Alembic migration `006_users.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | default `uuid4` |
| `username` | Text, unique, not null | |
| `password_hash` | Text, not null | bcrypt via passlib |
| `cv_text` | Text, nullable | extracted plain text from uploaded file |
| `created_at` | DateTime (tz) | server default |
| `updated_at` | DateTime (tz) | server default, on update |

No foreign keys to `jobs` or `companies` for now.

### Auth Routes — `backend/routers/auth.py`

- `POST /auth/register` — body: `{username, password}` → creates user, returns `{access_token, token_type}`
- `POST /auth/login` — body: `{username, password}` → verifies password, returns `{access_token, token_type}`
- `GET /auth/me` — requires Bearer token → returns `{id, username, has_cv}`

**JWT**: signed with `SECRET_KEY` env var, 7-day expiry, algorithm HS256. Library: `python-jose[cryptography]`.  
**Password hashing**: bcrypt via `passlib[bcrypt]`.  
**Auth dependency**: `get_current_user(token: str = Depends(oauth2_scheme))` — reusable FastAPI dependency that decodes the JWT and returns the User ORM object.

### CV Routes — `backend/routers/cv.py`

- `POST /users/cv` — multipart file upload (PDF / Word / plain text), extracts plain text, saves to `users.cv_text`. Returns `{message, char_count}`.
- `GET /users/cv` — returns `{cv_text, has_cv}` for the current user.

**Text extraction**:
- `.pdf` → `pdfplumber`
- `.docx` → `python-docx`
- `.txt` / plain text → read directly

Both routes require Bearer token (use `get_current_user` dependency).

### Modified Search — `backend/routers/search.py`

**Removed**: `cv_text` field from `SearchRequest`.  
**Added**: `get_current_user` dependency — reads `user.cv_text` from DB.  
**Behavior**: if `user.cv_text` is null, return HTTP 400 `{"detail": "No CV uploaded. Please upload your CV first."}`.  
**Request body** now: `{query: str, strict: bool = False}`.

Existing tests updated to mock an authenticated user with a pre-loaded CV text.

### New Dependencies (backend `pyproject.toml`)

```
python-jose[cryptography]
passlib[bcrypt]
python-multipart
pdfplumber
python-docx
```

### New Environment Variables

```
SECRET_KEY=...           # random secret for JWT signing, required
ACCESS_TOKEN_EXPIRE_DAYS=7
```

### CORS

Add `CORSMiddleware` to `main.py` allowing origin `http://localhost:3000`.

---

## Frontend

### Stack

- **Vite + React + TypeScript**
- No UI component library — plain CSS, keep it minimal
- `axios` for HTTP requests (or native `fetch`)
- `react-router-dom` for client-side routing

### Pages

#### `/login` — Login / Register

Single page, toggles between login and register mode.

- Fields: username, password
- On submit: calls `POST /auth/login` or `POST /auth/register`
- On success: stores JWT in `localStorage` as `access_token`, redirects:
  - → `/cv` if `has_cv` is false
  - → `/search` if `has_cv` is true

#### `/cv` — CV Upload

- Shows current CV status (uploaded / not uploaded)
- File drop zone accepting `.pdf`, `.docx`, `.txt`
- On upload: calls `POST /users/cv` with multipart form
- "Go to Search" button (enabled once CV exists)
- "Update CV" link to re-upload

#### `/search` — Search Jobs

- Text input for query
- "Strict mode" checkbox
- On submit: calls `POST /jobs/search` with `{query, strict}` + Bearer token header
- Results list: title, company name, location, employment type, seniority, languages
- Footer links: "Update CV" → `/cv`, "Logout" → clears `localStorage`, redirects to `/login`

### Routing Logic

```
Not authenticated → /login
Authenticated, no CV → /cv
Authenticated, has CV → /search
```

A top-level `PrivateRoute` wrapper checks `localStorage` for the token and fetches `/auth/me` to verify. If the token is missing or invalid, redirects to `/login`.

### Directory Structure

```
frontend/
  src/
    api/          # axios client, typed request functions
    pages/
      Login.tsx
      CV.tsx
      Search.tsx
    components/
      PrivateRoute.tsx
      JobCard.tsx
    App.tsx       # router setup
    main.tsx
  index.html
  vite.config.ts
  package.json
  Dockerfile
```

### Docker

**`frontend/Dockerfile`** — multi-stage: build with Node, serve with nginx.

```yaml
# docker-compose.yml addition
frontend:
  build:
    context: ./frontend
    args:
      VITE_API_URL: http://localhost:8000
  ports:
    - "3000:80"
```

Note: `VITE_API_URL` is a build-time arg (Vite embeds it at bundle time, not runtime). Pass it via `build.args` in docker-compose, and declare it as `ARG VITE_API_URL` in the Dockerfile before `npm run build`.

---

## What Is Not In Scope

- Refresh tokens / token revocation
- Multiple CVs per user
- User settings / preferences page
- Relations between users and saved jobs
- Email / OAuth login
- Rate limiting

---

## Build Order

1. Alembic migration — `users` table
2. SQLAlchemy `User` model
3. Auth routes + JWT dependency
4. CV routes + text extraction
5. Update search router + tests
6. CORS middleware
7. Frontend scaffold (Vite + React)
8. Login page
9. CV upload page
10. Search page
11. Docker + docker-compose wiring
