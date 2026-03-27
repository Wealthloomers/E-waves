# Elliott Wave Radar

Standalone daily-chart scanner for likely Elliott Wave C candidates.

This app is intentionally separate from the options scanners. It looks for:

- a completed Wave A impulse
- a Wave B retracement that stays within a configurable retracement band
- early Wave C progression
- confirmation from daily RSI, volume expansion, and short-term EMA structure

It returns two ranked lists:

- `bullish_candidates`
- `bearish_candidates`

Each candidate includes:

- current price
- Wave A size
- Wave B retracement
- current Wave C progress
- primary Wave C target price
- stretch target price
- invalidation price
- expected days remaining for Wave C completion
- expected completion date and completion window

## Heuristic Basis

The scanner uses practical Elliott-wave heuristics rather than discretionary wave counting.

- Wave B is expected to retrace a meaningful portion of Wave A without fully invalidating it.
- The primary Wave C price target assumes Wave C is approximately equal to Wave A.
- The stretch target assumes Wave C extends to `1.618 x Wave A`.
- The base Wave C time estimate centers on the duration of Wave A, with a wider Fibonacci-style window from `0.618x` to `1.618x` of Wave A duration.

These are probabilistic estimates, not guarantees.

## Backend

Entry point:

- `backend/api.py`

Key endpoints:

- `GET /`
- `GET /status`
- `GET /results`
- `GET /defaults`
- `POST /defaults`
- `GET /universe`
- `POST /scan`
- `POST /cancel-scan`
- `POST /refresh-universe`

Environment variables:

- `POLYGON_API_KEY`
- `SCAN_API_KEY`
- `ALLOWED_ORIGINS`

## Frontend

Entry point:

- `frontend/src/App.jsx`

Main UI features:

- persisted defaults
- universe refresh
- live scan and refresh progress
- bullish and bearish ranked tables
- Wave C timing and target output for every candidate

## Deploy

Railway:

- root directory: `elliott-wave-scanner/backend`

Vercel:

- root directory: `elliott-wave-scanner/frontend`

Frontend environment variable:

- `VITE_API_URL=https://<your-railway-domain>`
