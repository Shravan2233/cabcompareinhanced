# Live Cab Fare Integration Research Report

**Project:** CabCompare  
**Providers Investigated:** Uber, Ola, Rapido, Namma Yatri  
**Test Corridor:** Indiranagar (`12.9784, 77.6408`) → MG Road (`12.9756, 77.6066`), Bengaluru, India  
**Research Date:** 2026-11-23  

---

## 1. Executive Summary

No public, unauthenticated API exists from **Uber**, **Ola**, **Rapido**, or **Namma Yatri** that returns live, bindable cab fares for third-party web applications without developer/partner credentials or an authenticated user session.

Key conclusions:

1. **No zero-key live official endpoints exist:** Every official or reverse-engineered provider quote endpoint tested with real Bengaluru coordinates returned `401 Unauthorized`, `403 Forbidden`, an error payload requiring a user session cookie, or failed DNS resolution (`getaddrinfo failed`) for internal mobile subdomains (`auth.rapido.bike`, `api.nammayatri.in`).
2. **Existing GitHub "no-API-key" projects fall into three patterns:**
   - **Mock-data wrappers (`buildwithanuragpandey/cab-compare`):** Require manual user/partner tokens (`UBER_TOKEN`, `OLA_TOKEN`, `RAPIDO_TOKEN` + `RAPIDO_DEVICE_ID`, `NAMMA_YATRI_TOKEN`) and silently substitute Haversine math mocks (`isMock: true`) whenever tokens are absent.
   - **Pure mathematical rate-card calculators (`adikarthikeya/ride-fare-india`, `vojjala-sravya/ridecompare`):** Compute distance/time formulas (or add `random(0..15%)`) and explicitly acknowledge they do not fetch live prices.
   - **Deep-linking + User-Assisted Fare Capture (`ChandraChaan/cab-fare-compare`):** Launches the official provider apps/universal links (with route prefill where supported) and lets the user record the exact fare they just saw inside the official app.
3. **Production web comparators (`catchaprice.com/ride`, `rozmo.in/cab-price-compare/`) rely on authenticated user sessions, browser extensions, or private server-side pooled sessions:**
   - **CatchAPrice** asks users for Uber cookies (`cookie_string` via Chrome extension `lpaambncpajekeiflmfffmdhjndmeifd` or auth flow) and Ola OTP login (`phone` + `wasc_cookie` + `device_cookies`). Calling its unauthenticated Uber/Ola endpoints returned `502` and `401`.
   - **Rozmo** exposes a rate-limited guest search proxy returning live-looking `fixed` quotes for Ola, Rapido, and Namma Yatri from its own backend, while explicitly marking Uber as `"state": "app_only"` (`"Compare Uber in the Rozmo app"`), proving Uber cannot be pulled anonymously on the server. Using third-party commercial aggregator endpoints without authorization violates rate limits and reliability guarantees.
4. **Honest path without 4 developer API keys:**
   - Keep **optional authorized backend integrations** (partner/OAuth tokens or user-authorized session tokens via environment variables, plus ONDC Buyer App (BAP) webhook/gateway support for Namma Yatri) isolated in per-provider backend services with strict timeouts and rate limits.
   - Never fabricate or substitute formula/RTA prices when genuine provider quotes cannot be retrieved: return **`UNAVAILABLE`** with an explicit reason.
   - Pair every card with **working deep links** (`m.uber.com/looking` and `book.olacabs.com` with verified route prefill; `rapido.bike` / Play Store and `nammayatri.in` / Play Store honestly marked `prefillsRoute: false`) plus optional **User-Assisted Fare Capture** so riders can compare real fares they observe inside the official apps.

---

## 2. Existing Codebase Audit

Inspected before making any modifications:

- **Backend (`Flask 3.0.3`):**
  - `backend/app.py`: Exposes `/api/health`, `/api/providers`, `/api/places/suggest`, `/api/places/reverse`, `/api/routes/popular`, `/api/rides/compare`.
  - `backend/services/routing.py`: Uses Komoot Photon + OpenStreetMap Nominatim + OSRM public demo routing + offline `INDIAN_LANDMARKS`. Free, API-keyless geocoding & routing works in Bengaluru.
  - `backend/services/fares.py` & `backend/services/estimates.py`: `uber_fares()` calls `api.uber.com/v1.2/estimates/price` (gated by `UBER_SERVER_TOKEN` and `UBER_COMPARISON_APPROVED=true`); `ola_fares()` calls `devapi.olacabs.com/v1/products` (gated by `OLA_APP_TOKEN`). **Critical flaw:** `comparison_rides()` falls back to city RTA rate-card formulas (`backend/providers/rates.py`) whenever live quotes fail, displaying computed estimates across Uber, Ola, Rapido, and Namma Yatri as default comparison prices.
  - `backend/providers/{uber,ola,rapido,namma_yatri}.py`: Contain only static display metadata (`PROVIDER` dicts), not independent fare-retrieval modules.
  - `backend/providers/links.py`: Builds `m.uber.com/looking` (prefilled JSON), `book.olacabs.com` (prefilled coordinates), `www.rapido.bike/` (`prefilled: False`), `nammayatri.in/` (`prefilled: False`).
  - `backend/models/`: Contains scikit-learn training scaffolding (`RandomForestRegressor`); `fare_model.joblib` does not exist.
  - `database/{schema,seed}.sql`: MySQL schema unused by Flask API endpoints.
- **Frontend (`React 18` + `Vite` + `Tailwind CSS` + `Leaflet`):**
  - Interactive OpenStreetMap pickup/destination picker (`MapPickerModal.jsx`), autocomplete (`LocationInput.jsx`), OSRM route map (`RouteMap.jsx`), clipboard copy helpers (`App.jsx`).
  - Frontend tests: none; Backend tests: `backend/tests/` (44 tests covering existing behavior).

---

## 3. Provider-by-Provider Investigation

### Summary Matrix (Questions 1–8)

| Criterion | Uber | Ola | Rapido | Namma Yatri |
| :--- | :--- | :--- | :--- | :--- |
| **Q1. Public unauthenticated fare endpoint?** | No | No | No | No (ONDC BAP registration required) |
| **Q2. Authentication required?** | Yes (OAuth 2.0 Bearer / approved Server Token, or rider session + CSRF + Cloudflare) | Yes (Invite-only `X-APP-TOKEN`, or OTP rider `wasc` session cookie) | Yes (Mobile OTP JWT + `deviceid`, or corporate integration) | Yes (Authorized rider token or signed ONDC Beckn BAP keys) |
| **Q3. Actual quote without API key?** | **No** (`HTTP 401` / `403`) | **No** (`HTTP 401` / `UNKNOWN_ERROR` 1500) | **No** (no public web API; DNS failed on `auth.rapido.bike`) | **No** (requires ONDC BAP onboarding or authorized token) |
| **Q4. Can a user-authorized session be used?** | Technically on `riders.uber.com` / `m.uber.com/go/graphql` if user authorizes own session, but Cloudflare blocks headless requests (`HTTP 403`) & fragile | Technically via user OTP login to web booking session (`book.olacabs.com`), brittle & against standard ToS for automated third-party apps | Requires user OTP login + app headers; fragile (Protobuf/schema drift) & against ToS | Technically via user bearer token or properly registered ONDC Buyer App |
| **Q5. Returned fare shape** | Range (`low_estimate`–`high_estimate`) + surge multiplier (`FARE_ESTIMATE` via official API) | Exact/range per category (`total_fare` or min/max) | Fixed or tight range depending on service & endpoint | Upfront estimated/fixed quote via `on_search` estimates |
| **Q6. Works in India?** | Yes | Yes | Yes | Yes |
| **Q7. Supports Bengaluru?** | Yes | Yes | Yes | Yes (primary launch city) |
| **Q8. Key legal / technical limits** | Official ToS §II.B explicitly prohibits price comparison; Cloudflare/CSRF on web endpoints | Partner API invite-only (`affiliates@olacabs.com`); `book.olacabs.com` rejects anonymous p2p calls | No public developer portal; OTP-gated app APIs | Open-source stack (`nammayatri/nammayatri`), but production ONDC access requires registered BAP entity & cryptographic signing |

---

### Detailed Provider Findings & Documented Endpoints

#### 1. Uber
- **Official Estimate Endpoint:** `GET https://api.uber.com/v1.2/estimates/price` (or Uber Guest Rides API `POST /v1/guests/trips/estimates`).
  - **Authentication:** OAuth 2.0 Client Credentials / User Bearer token or deprecated Server Token. Requires explicit Uber Business Development approval.
  - **Pricing Format:** Returns currency code, distance, duration, surge multiplier, and **`low_estimate` / `high_estimate` range** (`FARE_ESTIMATE`).
  - **ToS Restriction:** Uber Developer API Terms of Use (§II B) strictly forbid using the Uber API for competitive price comparison with third-party ride providers without explicit approval.
- **Unofficial Web Endpoint:** `POST https://riders.uber.com/api/getFareEstimateAction` / `https://m.uber.com/go/graphql`.
  - Protected by Cloudflare bot challenges (`HTTP 403 Just a moment...`), CSRF headers (`x-csrf-token`), and user `sid` cookies.
- **Official Universal Deep Link:** `https://m.uber.com/looking?pickup=<JSON>&drop[0]=<JSON>` (or `https://m.uber.com/ul/?action=setPickup&...`).
  - Live probe confirmed `m.uber.com/looking` returns `HTTP 200` and preserves encoded pickup & drop-off JSON across desktop and mobile (`m.uber.com/go/home`), whereas `m.uber.com/ul/` redirected on desktop to `https://www.uber.com/in/en/ride/?referrer=singular_click_id=...` without visible coordinate params.

#### 2. Ola
- **Official Partner API:** `GET https://devapi.olacabs.com/v1/products` (with `pickup_lat`, `pickup_lng`, `drop_lat`, `drop_lng`).
  - **Authentication:** Requires invite-only `X-APP-TOKEN` (and user Bearer token for booking) obtained via `affiliates@olacabs.com`; Ola shifted self-serve developer portals toward Ola Maps / Krutrim Cloud.
  - Live probe unauthenticated: `HTTP 401 {"code":"invalid_partner_key","message":"Partner key is not authorized"}`.
- **Consumer Web Booking Endpoint:** `GET https://book.olacabs.com/data-api/category-fare/p2p`.
  - Live probe unauthenticated: `HTTP 200 {"data":null,"error":{"code":"UNKNOWN_ERROR","message":"We were unable to process your request. Please try again.","status":1500}}` — requires authenticated OTP web session cookies (`wasc`).
- **Deep Link:** `https://book.olacabs.com/?lat=...&lng=...&drop_lat=...&drop_lng=...&pickup_name=...&drop_name=...` and Android app URI `olacabs://app/launch?...` (`com.olacabs.customer`).
  - Live probe of `book.olacabs.com` returned `HTTP 200` with query params preserved. (Official Ola affiliate docs also note `utm_source` as a tracking parameter.)

#### 3. Rapido
- **API Status:** No public consumer fare API or open developer portal; Rapido only offers managed **Rapido Corporate** enterprise onboarding.
- **Reverse-Engineered Mobile Endpoints:** Community code targets internal gateways (`auth.rapido.bike/om/api/orders/v2/rideAmount`), requiring mobile OTP JWT (`Bearer`) + `deviceid` + app headers (`appid`, `appversion`) and evolving protobuf/payload validation.
- **DNS Test:** `auth.rapido.bike` failed DNS resolution from the public internet (`getaddrinfo failed`), confirming it is deprecated, geo/app-restricted, or internal.
- **Deep Link:** `https://www.rapido.bike/` and Android package `com.rapido.passenger`. Does **not** officially support public route prefill from external web links (`prefillsRoute: false`).

#### 4. Namma Yatri
- **Architecture:** Open-source Haskell/Juspay backend (`github.com/nammayatri/nammayatri`) built on **ONDC / Beckn Protocol** (`search` -> `on_search`, `select` -> `on_select`).
- **API Status:** Direct endpoints like `api.nammayatri.in/v2/rideSearch` do not resolve publicly (`getaddrinfo failed` during test); `api.moving.tech` resolves (`16.4.66.120`) as MovingTech infrastructure, requiring authorized rider bearer tokens or ONDC network registration.
- **ONDC Integration Requirement:** Integrating legitimately across Namma Yatri and other ONDC sellers requires registering as an Indian corporate entity in the **ONDC Network Participant (NP) Registry**, implementing Beckn webhooks (`/on_search`, `/on_select`) with Ed25519 request signing, clearing staging conformance tests, and obtaining Production Registry approval.
- **Deep Link:** `https://nammayatri.in/` and Android package `in.juspay.nammayatri`. Upstream `AndroidManifest.xml` defines only `MAIN` / `LAUNCHER` intent filters with no URL query/route prefill (`prefillsRoute: false`).

---

## 4. Inspection of Reference GitHub Repositories

| Repository | Mechanism Inspected | Works Without API Keys? | Suitable for Production? | Findings |
| :--- | :--- | :--- | :--- | :--- |
| **[buildwithanuragpandey/cab-compare](https://github.com/buildwithanuragpandey/cab-compare)** | Node/Express calling provider endpoints + hardcoded mock fallbacks + `comparify.js` scraper | **No** (returns fake Haversine math `getMock*Fares` with `isMock: true` when env tokens are missing) | **No** | Inspecting `src/services/{uber,ola,rapido,nammaYatri}.js` confirmed every file checks `UBER_TOKEN` (or `sid` cookie on `riders.uber.com`), `OLA_TOKEN` (`devapi.olacabs.com`), `RAPIDO_TOKEN` + `RAPIDO_DEVICE_ID` (`auth.rapido.bike`), and `NAMMA_YATRI_TOKEN` (`api.nammayatri.in`), falling back to hardcoded math formulas when unset. `comparify.js` also calls `cabs.comparify.pro/api/cabs` with a hardcoded salt (`cmpf_9f3b61a72e4d5c88`), creating IP-block and ToS risks. |
| **[adikarthikeya/ride-fare-india](https://github.com/adikarthikeya/ride-fare-india)** | Pure rate-card model (`fare_engine.py` + `fare_config.json`) + Open-Meteo weather + IST peak multipliers | Uses no ride APIs (only Open-Meteo weather) | **Only as explicitly labeled simulator** | Explicitly warns in `README.md` that fares are **rule-based estimates**, not live provider quotes. |
| **[vojjala-sravya/ridecompare](https://github.com/vojjala-sravya/ridecompare)** | Single-file HTML calling Nominatim + OSRM, computing `Base + PerKm * km + random(0..15%)` | Uses no ride APIs | **No** | Adds synthetic random jitter (`0..15%`) over a base+per-km formula. `readme.md` explicitly admits no public provider APIs exist. |
| **[ChandraChaan/cab-fare-compare](https://github.com/ChandraChaan/cab-fare-compare)** | Offline Flutter Android app (no `INTERNET` permission in `AndroidManifest.xml`) + Deep Links + **User-Assisted Fare Capture** | **Yes** (relies on user seeing real fare in official apps) | **Yes (truthful & compliant)** | Launches Uber (`uber://?` / `m.uber.com/ul/?`) and Ola (`book.olacabs.com/?lat=...&drop_lat=...`) prefilled, and opens Rapido/Namma Yatri (`market://launch?id=...`, `prefillsRoute: false`). On app resume within 15 minutes (`WidgetsBindingObserver`), asks the user what fare they observed and stores per-route median history locally. |

---

## 5. Inspection of Third-Party Comparison Websites

### A. `https://catchaprice.com/ride`
- **Inspected Source (`assets/index-CwkVTvzd.js`):** Calls `https://api.catchaprice.com/api/ride/*` plus integrates an optional browser extension (`CATCHAPRICE_EXTENSION_ID = "lpaambncpajekeiflmfffmdhjndmeifd"`).
- **How it obtains fares:**
  - **Uber (`/api/ride/uber/prices`):** Accepts `cookie_string` from `/api/ride/uber/start-auth` or the Chrome extension. Probed without cookies on Bengaluru coordinates → **`HTTP 502 {"detail":"Uber rejected the request (session expired or rate limited)"}`**.
  - **Ola (`/api/ride/ola/prices`):** Requires user OTP login (`/api/ride/ola/login`, `/api/ride/ola/verify-otp`) passing `phone`, `wasc_cookie`, `fingerprint`, `device_cookies`. Probed without auth → **`HTTP 401 {"detail":"Not authenticated. Please login first."}`**.
  - **Namma Yatri (`/api/ride/namma-yatri/prices`):** Probed without auth → **`HTTP 200 {"quotes":[],"city":null,"is_live_price":false,"session_expired":false,"search_id":null}`** (empty).
  - **Rapido (`/api/ride/rapido/prices`):** Returned **`HTTP 200`** range estimates (`min_price`/`max_price`, e.g., Bike Direct `61–74`, Auto `109–130`), while `/api/ride/local-taxi/prices` returned Bengaluru metered auto/taxi ranges (`distance: 5.64`).
- **Suitability:** Cannot be called as an upstream source for our app (unowned third-party API, requires user cookie harvesting for Uber/Ola, violates attribution/rate-limit norms if leeched).

### B. `https://rozmo.in/cab-price-compare/`
- **Inspected Source (`/assets/cab_index-Camjxirv.js`):** Thin web teaser calling `https://api.rozmo.in/api/rides/guest/search/` with strict guest rate limiting (`HTTP 429` `"Free search limit reached"` pushing users to `/download` mobile apps).
- **Live Bengaluru Probe (`HTTP 200`):** Returned `route: {distance_m: 5360, duration_s: 1206}` and:
  - `bharat_taxi`: `state: "unavailable"`
  - `namma_yatri`: `6` fixed quotes (e.g., Auto `₹143`, AC Priority `₹190`)
  - `rapido`: `11` fixed quotes (e.g., Bike Direct `₹56`, Auto `₹147`)
  - `ola`: `11` fixed quotes (e.g., Bike `₹112`, Auto `₹120`)
  - **`uber`: `state: "app_only"`, `quotes: 0`, `"Compare Uber in the Rozmo app"`**
- **Key Takeaway:** Even a funded commercial aggregator cannot retrieve Uber live prices anonymously on the web without user-side/in-app assistance (`"app_only"`). Its Ola/Rapido/Namma Yatri backend relies on proprietary server-side session pools under tight guest rate limits; proxying `api.rozmo.in` would breach third-party service terms and break immediately on IP throttling.

---

## 6. Alternative Integration Approaches Evaluated

| Approach | How It Works | Actual Quote or Estimate? | Feasibility & Verdict |
| :--- | :--- | :--- | :--- |
| **Distance/RTA Rate-Card Formula** | Compute `base + per_km * km + per_min * min` | Calculated estimate | **NOT acceptable as a replacement for live quotes** — never reflects dynamic surge, driver supply, or exact promo/platform pricing. |
| **ONDC Mobility (Beckn BAP)** | Registered Buyer App sends signed `/search` to gateway and receives live `/on_search` quotes (covers Namma Yatri & ONDC fleets) | **Actual Quote (`LIVE_QUOTE`)** | **PARTIALLY VERIFIED** — Technically real and legal, but **requires corporate entity registration, ONDC conformance sign-off, Ed25519 keys, and public webhook hosting** (`>= several weeks`), not zero-setup without credentials. |
| **User-Authorized Provider Sessions** | Backend uses user/developer-supplied authorized tokens (`env` or explicit authorized session config) | **Actual Quote (`LIVE_QUOTE` / `FARE_ESTIMATE`)** | **UNVERIFIED without valid creds** — Architecturally supported on backend via independent modules, never hardcoded/scraped/logged. |
| **Android Intents & Universal Links** | Launch official apps with pickup/drop prefilled (Uber/Ola) or app home (Rapido/Namma Yatri) | N/A (hands off to live quote screen) | **VERIFIED WORKING** for Uber & Ola web/universal prefill; **PARTIALLY VERIFIED** (`prefillsRoute: false`) for Rapido & Namma Yatri. |
| **Android `AccessibilityService` Screen Reading** | Read fares displayed inside Uber/Ola/Rapido/NY UIs on user's Android device | Reads actual UI fare | **NOT FEASIBLE for Play Store distribution** — Google Play strictly restricts `AccessibilityService` to disability tools (`isAccessibilityTool="true"` verification), bans unapproved third-party screen scraping, requires Prominent Disclosure + video review, and Android supports `isAccessibilityDataSensitive` layout masking. |
| **Browser Extension (Content Script / User Tab)** | Like CatchAPrice Chrome Extension, runs in the user's own logged-in browser tab | Reads actual fare in user session | **PARTIALLY VERIFIED (Conceptual)** — Requires building/distributing a browser extension and only works where web booking exists (`m.uber.com`, `book.olacabs.com`); Rapido & Namma Yatri lack full public web booking flows. |
| **User-Assisted Fare Capture** | Deep-link to provider app; user enters the exact fare they saw back into CabCompare for side-by-side comparison & route memory | **User-Observed Actual Quote** | **VERIFIED WORKING** — Zero API keys, zero ToS/Play policy risk, 100% real numbers seen directly by the rider. |

---

## 7. Legal, Privacy, and Terms-of-Service Constraints

1. **Uber API Terms of Use (§II.B):** Prohibits price-comparison integrations using Uber's official developer APIs without explicit written permission from Uber.
2. **India IT Act, 2000 (Sections 43 & 66):** Extracting data from computer systems without owner permission—especially bypassing rate limits, Cloudflare challenges, CSRF tokens, or ToS prohibitions—creates civil compensation liability (§43) and criminal risk (§66) if deemed dishonest intrusion.
3. **Digital Personal Data Protection (DPDP) Act, 2023:** Scraping or storing user account identifiers, phone numbers, session cookies (`sid`, `wasc`), or booking histories triggers **Data Fiduciary** obligations requiring explicit consent, purpose limitation, and security safeguards.
4. **Google Play Store Policy:** Non-disability `AccessibilityService` screen scraping for fare comparison violates core Play Store rules and triggers app removal.
5. **Third-Party Aggregators (`rozmo.in`, `catchaprice.com`, `comparify.pro`):** Extracting reverse-engineered API salts or querying private commercial backends from our server violates third-party ToS and induces immediate IP bans (`429`/`403`).

---

## 8. Bengaluru Verification Test Results (`12.9784, 77.6408` → `12.9756, 77.6066`)

All probes executed on `2026-11-23` without forged credentials or CAPTCHA/rate-limit bypasses:

| Target | Method & Request | Result | Classification |
| :--- | :--- | :--- | :--- |
| Uber Official Estimate API | `GET api.uber.com/v1.2/estimates/price` (unauth) | `HTTP 401 Invalid OAuth 2.0 credentials provided.` | **NOT FEASIBLE (without API key & approval)** |
| Uber Riders Internal Web | `POST riders.uber.com/api/getFareEstimateAction` (unauth) | `HTTP 403` Cloudflare `"Just a moment..."` | **NOT FEASIBLE** |
| Uber Mobile GraphQL | `POST m.uber.com/go/graphql` (`{__typename}`) | `HTTP 403 Missing csrf token.` | **NOT FEASIBLE (without session)** |
| Ola Partner API | `GET devapi.olacabs.com/v1/products` (unauth) | `HTTP 401 {"code":"invalid_partner_key"}` | **NOT FEASIBLE (without invite-only token)** |
| Ola Web Booking API | `GET book.olacabs.com/data-api/category-fare/p2p` (unauth) | `HTTP 200 {"data":null,"error":{"code":"UNKNOWN_ERROR","status":1500}}` | **NOT FEASIBLE (without OTP session cookie)** |
| Rapido Mobile Order API | `POST auth.rapido.bike/om/api/orders/v2/rideAmount` | DNS failure (`getaddrinfo failed`) | **NOT FEASIBLE** |
| Namma Yatri Direct API | `POST api.nammayatri.in/v2/rideSearch` | DNS failure (`getaddrinfo failed`) | **NOT FEASIBLE (direct public call)** |
| Uber Deep Link | `GET m.uber.com/looking?pickup=...&drop[0]=...` | `HTTP 200 -> m.uber.com/go/home` (pickup & drop JSON preserved) | **VERIFIED WORKING** |
| Uber `m.uber.com/ul` | `GET m.uber.com/ul/?action=setPickup...` | Redirected to `uber.com/in/en/ride/?referrer=singular_click_id=...` on desktop | **PARTIALLY VERIFIED** (prefer `m.uber.com/looking`) |
| Ola Deep Link | `GET book.olacabs.com/?lat=...&drop_lat=...` | `HTTP 200` (pickup & drop query params preserved) | **VERIFIED WORKING** |
| Rapido Link / Play Store | `GET www.rapido.bike/Home` & `play.google.com/...com.rapido.passenger` | `HTTP 200` (home page/store only; no route prefill) | **PARTIALLY VERIFIED (`prefillsRoute: false`)** |
| Namma Yatri Link / Play Store | `GET nammayatri.in/` & `play.google.com/...in.juspay.nammayatri` | `HTTP 200` (`AndroidManifest.xml` confirms `MAIN`/`LAUNCHER` only) | **PARTIALLY VERIFIED (`prefillsRoute: false`)** |
| OpenStreetMap Geocoding & OSRM Routing | Existing `backend/services/routing.py` (Photon/Nominatim + OSRM) | Returns Bengaluru stops & `~5.3–5.6 km` road route without keys | **VERIFIED WORKING** |

---

## 9. Recommended Architecture for CabCompare

1. **Remove fake/formula prices from live comparison paths:**
   - Refactor `comparison_rides()` so unauthenticated providers return `quoteType: "UNAVAILABLE"` and `status: "unavailable"` with clear explanations—never distance-card approximations disguised on the comparison grid.
2. **Modular Provider Services (`backend/providers/{uber,ola,rapido,namma_yatri}.py`):**
   - Each provider becomes an independent service exposing `fetch_quotes(pickup, drop, config)` returning standardized objects:
     - `provider`, `vehicleType`, `fare`, `fareRange` (`min`, `max`), `currency` (`"INR"`), `etaMinutes`, `quoteType` (`LIVE_QUOTE` | `FARE_ESTIMATE` | `UNAVAILABLE`), `retrievedAt` (ISO UTC), `status` (`"success"` | `"unavailable"`), `error` / availability reason, and honest deep link metadata (`url`, `androidIntent`, `prefillsRoute`).
   - Support authorized backend credentials cleanly (`UBER_SERVER_TOKEN` + `UBER_COMPARISON_APPROVED=true` or OAuth token; `OLA_APP_TOKEN`; optional authorized gateway URLs/tokens via backend env vars for Rapido & Namma Yatri / ONDC BAP), with strict HTTP timeouts (`5s`), in-memory rate limiting per client IP, short TTL quote caching, and safe token redaction in logs/errors.
3. **Honest Deep Linking + User-Assisted Fare Capture:**
   - Surface accurate prefill status on every CTA (`"Pickup & drop prefilled"` for Uber/Ola vs `"Opens home screen — enter pickup & drop in app"` for Rapido/Namma Yatri, plus Android `intent://` deep links where helpful on mobile).
   - Provide an optional client-side **"Log fare you saw"** capture control so users opening Uber/Ola/Rapido/Namma Yatri on their phone can record actual quoted fares side-by-side for that route—kept explicitly separate and badged `"User-entered fare"` rather than fabricated by formulas.
4. **Clear UI Distinction:**
   - Clearly differentiate `LIVE_QUOTE`, `FARE_ESTIMATE`, `UNAVAILABLE`, and any user-recorded comparison notes, and compute "Cheapest available quote" exclusively across genuine provider quotes (`LIVE_QUOTE` / `FARE_ESTIMATE`), never across `UNAVAILABLE` or synthetic numbers.
