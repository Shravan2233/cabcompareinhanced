# CabCompare

CabCompare compares ride options across **Uber**, **Ola**, **Rapido**, and **Namma Yatri** from a single route search. It works out of the box with **zero API keys** using free OpenStreetMap services (`Photon`, `Nominatim`, `OSRM`, and `Leaflet` tiles), an Uber/Ola-style center-pin mobile map picker, calibrated Indian city tariff estimates (`FARE_ESTIMATE`), prefilled booking deep links where supported, and device-local user fare capture (**Log fare seen**).

When authorized provider API or ONDC Buyer App (BAP) credentials are configured on the backend, genuine live quotes (`LIVE_QUOTE` / provider `FARE_ESTIMATE`) take priority over local rate-card estimates.

See [`docs/FARE_INTEGRATION_RESEARCH.md`](docs/FARE_INTEGRATION_RESEARCH.md) for the live endpoint probe results, repository audits, legal/Terms-of-Service analysis, and deep-link breakdown.

---

## What Works Without API Keys

- **Location autocomplete & reverse geocoding:** Komoot Photon + OpenStreetMap Nominatim + offline Indian city hubs ([`backend/services/routing.py`](backend/services/routing.py)).
- **Free interactive maps (zero watermarks / keys):** OpenStreetMap raster tiles (`tile.openstreetmap.org` with `tile.openstreetmap.fr/hot` fallback) via Leaflet in [`frontend/src/MapPickerModal.jsx`](frontend/src/MapPickerModal.jsx) (center drop-pin picker) and [`frontend/src/RouteMap.jsx`](frontend/src/RouteMap.jsx) (OSRM road route geometry).
- **Calibrated city rate-card fare estimates:** Computes realistic INR ranges from OSRM road distance, traffic-adjusted duration, city tariff slabs (**Bengaluru**, **Mumbai**, **Delhi NCR**, **Hyderabad**, **Chennai**, and an India default), and IST time-of-day periods (morning peak, evening peak, night tariff) in [`backend/providers/rates.py`](backend/providers/rates.py). Always badged `ESTIMATED FARE` rather than pretending to be a live provider quote.
- **Provider booking handoff:**
  - **Uber** (`m.uber.com/looking`) and **Ola** (`book.olacabs.com`): Pre-filled pickup and drop coordinates/addresses (`prefills_route: true`).
  - **Rapido** (`www.rapido.bike`) and **Namma Yatri** (`nammayatri.in`): Open the provider app/home page honestly marked `prefills_route: false` and copy your route to clipboard on click.
- **User-Assisted Fare Capture:** Click **Log fare seen** on any card after opening the provider app to store actual quoted prices per route in browser `localStorage`.

---

## Prerequisites (Download on a Fresh Laptop)

Install these before cloning or running the project:

1. **Git:** [https://git-scm.com/downloads](https://git-scm.com/downloads)
2. **Python 3.10+** (recommended 3.11 or 3.12): [https://www.python.org/downloads/](https://www.python.org/downloads/)
   - **Windows installer:** Check **"Add python.exe to PATH"** before clicking Install.
3. **Node.js 20 LTS+** (includes `npm`): [https://nodejs.org/](https://nodejs.org/)
4. *(Optional)* **MySQL 8+:** Not required to run the app right now. Schema and seed scripts live in `database/` for future persistence phases.

---

## Quick Start (First-Time Setup on a New Laptop)

### 1. Clone the repository

```bash
git clone <your-fork-or-repo-url>
cd cabcompareinhanced
```

### 2. Set up the Python backend

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
py -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

> **If PowerShell blocks `Activate.ps1`:** Run this once, then activate again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**macOS / Linux:**

```bash
cp .env.example .env
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

*(What this installs from [`backend/requirements.txt`](backend/requirements.txt): `Flask==3.0.3`, `python-dotenv==1.0.1`, `mysql-connector-python==8.3.0`, `joblib==1.4.2`, `pandas==2.2.3`, `scikit-learn==1.6.1`.)*

### 3. Set up the React frontend

**Windows (PowerShell):**

```powershell
cd frontend
Copy-Item .env.example .env
npm install
```

**macOS / Linux:**

```bash
cd frontend
cp .env.example .env
npm install
```

*(Installs React 18, Vite 6, Leaflet 1.9, Lucide icons, Axios, Recharts, and Tailwind CSS into `frontend/node_modules/`.)*

---

## Running the Application

### Option A: Single Command (Recommended)

From the `frontend/` directory:

```bash
npm run dev
```

Vite starts on `http://localhost:5173` (and binds `0.0.0.0` for LAN access). Its dev plugin in [`frontend/vite.config.js`](frontend/vite.config.js) automatically checks port `5000` and launches `backend/.venv` Flask (`python -m backend.app`) in the background if the backend is not already running.

Open **`http://localhost:5173`** in your browser.

### Option B: Separate Terminals (If you edit Python files often)

**Terminal 1 (from repo root):**

```powershell
.\backend\.venv\Scripts\python.exe -m backend.app
```

*(macOS/Linux: `./backend/.venv/bin/python -m backend.app`)* — starts the Flask API on `http://127.0.0.1:5000`.

**Terminal 2 (from `frontend/`):**

```bash
npm run dev
```

Vite detects port `5000` is already listening and proxies `/api/*` requests to your running Flask terminal.

---

## Previewing on Your Mobile Phone (Same Wi-Fi)

1. Run `npm run dev` inside `frontend/`. Vite prints a local network URL such as:
   ```text
   ➜  Network: http://192.168.x.x:5173/
   ```
2. Open that `http://192.168.x.x:5173` URL on your phone connected to the same Wi-Fi.
3. Because `/api/*` proxies through Vite on port `5173`, your phone does not need direct access to port `5000`.
4. **Windows Firewall note:** If the page times out on your phone, allow Node.js on **Private networks** when Windows Defender Firewall prompts, or temporarily check inbound rules for TCP port `5173`.
5. **GPS note on HTTP LAN:** Browsers only grant automatic geolocation (`navigator.geolocation`) on `localhost` or `HTTPS` origins. When opening over plain `http://192.168.x.x:5173` on a phone, type in the pickup box or tap **Pin on map** to position the center pin.

---

## Environment Variables (Optional Backend Integrations)

`.env` and `frontend/.env` are ignored by `.gitignore` — **never commit real tokens**. Leave provider credentials blank to use free OpenStreetMap routing + city rate-card estimates.

See [`.env.example`](.env.example):

- **Server & Guardrails:** `PORT` (`5000`), `FRONTEND_ORIGINS`, `RATE_LIMIT_COMPARE_PER_MIN` (`30`), `RATE_LIMIT_PLACES_PER_MIN` (`90`), `QUOTE_CACHE_TTL_SECONDS` (`45`)
- **Uber:** `UBER_OAUTH_TOKEN` or `UBER_SERVER_TOKEN`, `UBER_API_BASE_URL`, `UBER_COMPARISON_APPROVED=true` (required by Uber API Terms of Use §II.B for competitor comparison), optional `UBER_CLIENT_ID` for deep links
- **Ola:** `OLA_APP_TOKEN`, optional `OLA_BEARER_TOKEN`, `OLA_API_BASE_URL`, optional `OLA_AFFILIATE_UTM_SOURCE`
- **Rapido:** Optional authorized gateway `RAPIDO_API_URL`, `RAPIDO_AUTH_TOKEN`, `RAPIDO_DEVICE_ID`, optional `RAPIDO_LINK_TEMPLATE`
- **Namma Yatri (ONDC):** Optional registered ONDC Buyer App (BAP) gateway `NAMMA_YATRI_BAP_SEARCH_URL` and `NAMMA_YATRI_AUTH_TOKEN`
- **Optional Google Maps (`frontend/.env`):** Set `VITE_GOOGLE_MAPS_API_KEY` only if you want Google Places/Routes instead of free OpenStreetMap + OSRM.

---

## API Reference

- `GET /api/health` — Returns `{"status": "ok", "fare_mode": "hybrid"}`.
- `GET /api/providers` — Lists provider integration metadata without exposing secrets.
- `GET /api/places/suggest?q=...&lat=...&lng=...` — OpenStreetMap (Photon + Nominatim + Indian hubs) autocomplete.
- `GET /api/places/reverse?lat=...&lng=...` — Reverse geocoding for map pins / GPS coordinates.
- `GET /api/routes/popular` — Sample city routes for quick comparison.
- `POST /api/rides/compare` — Accepts JSON `{pickup, destination, pickup_coords?, destination_coords?, route_metrics?, category?, sort?}` and returns OSRM route metrics/geometry, normalized quotes (`quoteType`: `LIVE_QUOTE`, `FARE_ESTIMATE`, or `UNAVAILABLE`), `cheapest_quote`, and `booking` deep links (`prefills_route`). Rate-limited (`429 Retry-After`).

Supported filters/sorts: `category` in `all | bike | auto | sedan | premium`; `sort` in `cheapest | pickup | best_value`.

---

## Running Tests & Production Build

From the repository root (with `.venv` active or explicit Python path):

**Backend unit tests (Windows):**

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -v
```

*(macOS/Linux: `./backend/.venv/bin/python -m unittest discover -s backend/tests -t . -v`)*

**Frontend production build check (from `frontend/`):**

```bash
npm run build
```

---

## Project Structure

```text
├── .env.example                 # Root backend env template (copy to .env)
├── backend/
│   ├── app.py                   # Flask API + CORS + per-IP rate limiting
│   ├── requirements.txt         # Python dependencies
│   ├── providers/               # Independent provider modules (Uber, Ola, Rapido, Namma Yatri)
│   │   ├── base.py              # Shared HTTP client, timeout (5s), & quote schema normalization
│   │   ├── links.py             # Official deep links + truthful prefills_route metadata
│   │   ├── options.py           # Canonical 14 vehicle/provider options
│   │   └── rates.py             # Calibrated Indian city rate cards + IST peak/night tariffs
│   ├── services/
│   │   ├── comparison.py        # Route validation, metric parsing, cheapest quote ranking
│   │   ├── fares.py             # Concurrent provider fan-out + cache + rate-card fallback
│   │   ├── guards.py            # Sliding-window rate limiter & 45s TTL quote cache
│   │   └── routing.py           # Free Photon/Nominatim geocoding & OSRM road routing
│   ├── models/                  # Optional offline ML training schema/trainer
│   └── tests/                   # 34 backend unit tests (test_api, test_comparison, test_fares, test_routing)
├── database/                    # MySQL schema & seed scripts (optional future persistence)
├── docs/
│   └── FARE_INTEGRATION_RESEARCH.md  # Provider API/scraping/deep-link research report
└── frontend/
    ├── .env.example             # Frontend env template (copy to frontend/.env)
    ├── package.json             # Node scripts & dependencies
    ├── vite.config.js           # Vite dev server + LAN host + auto-start Flask API plugin
    └── src/
        ├── App.jsx              # Search, category tabs, fare cards, user fare capture
        ├── LocationInput.jsx    # Location autocomplete combobox
        ├── MapPickerModal.jsx   # Center drop-pin mobile & desktop Leaflet map picker
        ├── RouteMap.jsx         # OSRM route geometry map preview
        ├── leafletTiles.js      # Free OpenStreetMap tiles & teardrop pin SVG icons
        ├── maps.js              # Backend/optional Google Maps client helpers
        └── styles.css           # Responsive styles & mobile full-sheet map layout
```

---

## Troubleshooting

- **`connect ECONNREFUSED 127.0.0.1:5000` in Vite logs:** Ensure you created `backend/.venv` and ran `pip install -r backend\requirements.txt`. If needed, start Flask manually with `.\backend\.venv\Scripts\python.exe -m backend.app` from the repo root.
- **Map search or route lookup shows `"Searching places..."` / timeout:** Check internet connectivity — OpenStreetMap tiles (`tile.openstreetmap.org`), Photon (`photon.komoot.io`), Nominatim, and OSRM (`router.project-osrm.org`) require outbound HTTPS.
- **`pip install` fails on Windows:** Confirm Python 3.10–3.13 is installed with **"Add python.exe to PATH"** checked and run inside a fresh terminal.

---

## Notes Before Opening a Pull Request

- Check `git status` before staging to confirm `.env`, `frontend/.env`, `backend/.venv/`, `frontend/node_modules/`, and `frontend/dist/` are ignored by [`.gitignore`](.gitignore) and not staged.
