# Draft Night — V1

Private, league-specific fantasy-football live snake-draft application. Built from
`Draft_Night_V1_Spec_Sheet.pdf`.

## Stack

- **Backend:** FastAPI (Python 3.12) + SQLAlchemy + WebSockets
- **Frontend:** Next.js 15 + React + TypeScript + Tailwind
- **Database:** SQLite for dev (Postgres-ready via `DATABASE_URL`)

## Layout

```
backend/
  app/
    draft/         # core engine + validation + state snapshot (UI-independent)
    api/           # REST routes + WebSocket
    models.py      # ORM: leagues, teams, players, rankings, draft_slots, keepers, picks, draft_events
    schemas.py     # Pydantic models
    main.py        # FastAPI app
  tests/           # pytest: engine, validation, API
frontend/
  app/
    page.tsx                         # create league
    draft/[token]/admin/             # commissioner console
    draft/[token]/display/           # TV / projector view
    draft/[token]/team/[teamToken]/  # team mobile interface
  hooks/, components/, lib/          # real-time hook, draft board, API client
```

## Run (dev)

Backend (port 8000):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .   # makes the `app` package importable
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend (port 3000):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, create a league, and share the generated commissioner /
team / display links. To point the frontend at a different backend:

```bash
NEXT_PUBLIC_API_URL=http://<host>:8000 npm run dev
```

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q
```

`tests/e2e_flow.py` runs a full draft against a live server
(start the backend, then `.venv/bin/python tests/e2e_flow.py`).

## Draft model

- Server-side draft state is the single source of truth; clients submit actions and
  the authoritative state is broadcast over WebSockets.
- The draft runs on an explicit grid of slots. Pre-draft pick trades are modeled by
  editing a slot's `drafting_team_id` (no live-trading workflow in V1).
- Keepers are (team, player, round); they occupy the team's slot in that round and
  are pre-filled when the draft starts.
- States: `SETUP → READY → LIVE → COMPLETED`, with reopen + undo from the console.
- Access is token-based: `/draft/<league>/admin`, `/draft/<league>/team/<team>`,
  `/draft/<league>/display`.

## Out of scope for V1

Auction drafts, draft timers, live trading, waivers, weekly scoring, external
sleeper sync, chat, accounts/payments, and AI recommendations — per the spec.
