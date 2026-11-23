# CabCompare

CabCompare is a ride-comparison prototype with a responsive React/Vite interface and Flask API. Uber and Ola provider API estimates are optional and require backend credentials; when unavailable, clearly labelled route-based rate-card estimates are shown when route metrics exist. Rapido and Namma Yatri use a locally trained model where its data covers a ride, otherwise labelled rate-card estimates. Booking remains with the ride provider.

The existing locker application in the parent workspace is not modified by this project.

## Included

- Route search with required-field, length, and identical-location validation.
- Provider ride options, live provider API estimates where configured, trained-model predictions where available, and labelled route-based estimates for Rapido and Namma Yatri.
- Browser geolocation after an explicit user click. Coordinates are shown as the pickup text; no reverse geocoding or location history is performed.
- Device-local recent searches and sample popular routes.
- Flask health, provider-status, popular-route, and comparison endpoints.
- Provider status modules distinguish integrations requiring authorization from route-estimate-only providers.
- MySQL schema for accounts, routes, searches, providers, fare observations, preferences, and favorite routes.
- Python unit tests for the comparison engine and API responses.

## Run Locally

Requirements: Python 3.10+ and Node.js 20+ with npm. MySQL is optional for this demo release because the API does not persist searches or fares yet.

1. In PowerShell, create the local environment file and install backend dependencies:

   ```powershell
   cd cabcompare
   Copy-Item .env.example .env
   py -m venv backend/.venv
   .\backend\.venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt
   ```

2. Start the API from the `cabcompare` directory:

   ```powershell
   python -m backend.app
   ```

   API base URL: `http://127.0.0.1:5000`.

3. In a second terminal, install and start the frontend:

   ```powershell
   cd cabcompare/frontend
   Copy-Item .env.example .env
   npm install
   npm run dev
   ```

   Open `http://localhost:5173`.

## API

- `GET /api/health` reports backend health and the `hybrid` fare mode.
- `GET /api/providers` lists provider integration status.
- `GET /api/routes/popular` returns sample routes.
- `POST /api/rides/compare` accepts JSON such as `{"pickup":"Indiranagar, Bengaluru","destination":"MG Road, Bengaluru","category":"all","sort":"cheapest"}`.

Supported categories: `all`, `bike`, `auto`, `sedan`, `premium`. Sort values: `cheapest`, `pickup`, `best_value`. Each ride has `fare_status` of `live`, `model`, `estimated`, or `unavailable`; priced rows include currency and a fare/range, while unavailable rows include a reason. `fare_source` reports the status or `mixed`/`unavailable`. Availability is not asserted from fare estimates. An invalid request returns a JSON `error` and HTTP 400.

## Database

Create the local database schema and provider seed records with a MySQL account that has permission to create a database:

```powershell
mysql -u root -p < database/schema.sql
mysql -u root -p cabcompare < database/seed.sql
```

Database connection variables are placeholders in `.env.example`. The initial API does not yet read or write MySQL; the schema is supplied for the persistence phase. Do not store precise locations longer than needed, and obtain user consent before enabling account-linked search history.

## Maps and Provider Integrations

No mapping credentials are required: place suggestions and reverse geocoding use OpenStreetMap (Komoot Photon + Nominatim fallback + Indian city hubs), driving distance/geometry uses OSRM, and the interactive route map uses MapLibre GL with OpenFreeMap vector tiles. Google Maps can still be enabled optionally by setting `VITE_GOOGLE_MAPS_API_KEY`. Browser geolocation resolves coordinates into a readable address when available.

Fare access review (November 2026):

- **Uber:** Its official [price-estimate API](https://developer.uber.com/docs/riders/references/api/v1.2/estimates-price-get) accepts pickup/drop-off coordinates and returns a price range, but requires Uber approval. The [current API terms](https://developer.uber.com/docs/riders/terms-of-use) prohibit using Uber data in a competitive comparison or aggregated view unless explicitly permitted in writing. The API's [server-token guide](https://developer.uber.com/docs/riders/guides/authentication/server-token) says new server tokens are no longer granted. The adapter refuses to call the API unless an existing token and explicit `UBER_COMPARISON_APPROVED=true` are both configured after written authorization.
- **Ola:** Its developer documentation endpoint was unavailable for verification during this change. The backend adapter follows the requested `GET /v1/products` query and `X-APP-TOKEN` contract, but you must verify that endpoint/response schema and obtain authorized access with Ola before production use.
- **Rapido:** No public provider fare API was verified. CabCompare shows only a route-based estimate from the local rate card, not a live Rapido quote.
- **Namma Yatri:** Its [public repository](https://github.com/nammayatri/nammayatri) describes its ride-hailing platform as using Beckn/ONDC. That is a network-participant integration, not an open consumer estimate endpoint. Live search offers require approved network/BAP onboarding and credentials/keys.

Provider tokens are read only by the backend from `.env`/environment variables and are never sent to the frontend. Set `OLA_APP_TOKEN` to enable the requested Ola adapter. Set `UBER_SERVER_TOKEN` and `UBER_COMPARISON_APPROVED=true` only when Uber has explicitly approved this competitive comparison use in writing; a token alone is not sufficient. Optional `OLA_API_BASE_URL` and `UBER_API_BASE_URL` overrides are backend-only. When an API token is missing or a provider API fails, Uber and Ola use a route-based rate-card estimate if route metrics are available; without route distance/duration, the fare remains unavailable.

### Training the local fare model

Fare resolution for Uber/Ola is: valid live API quote, then a route-based rate-card estimate when route metrics are available. For Rapido/Namma Yatri, a trained model prediction is used for categories represented in the model, then the existing provider rate card. Model inference and training run only on the backend.

Uber/Ola route fallback applies provider multipliers to matching Bike, Auto, Sedan, and Premium rate-card calculations in `backend/providers/rates.py` and presents the result only as `ESTIMATED FARE`, never as a provider quote. All fallback fares require driving distance and duration; without route metrics the fare remains unavailable.

1. Collect **real, labeled fares** from authorized sources. Do not use synthetic rows or provider-app scraping. Each row represents an observed fare and its route features.
2. Use the columns in [`backend/models/fare_training_schema.csv`](backend/models/fare_training_schema.csv): `provider`, `vehicle`, `time_of_day`, `currency`, `distance_km`, `duration_minutes`, `pickup_lat`, `pickup_lng`, `destination_lat`, `destination_lng`, and `fare`. `time_of_day` must be `morning`, `afternoon`, `evening`, or `night` in India Standard Time. A dataset must have at least five complete labeled rows and contain a single currency.
3. From the `cabcompare` directory, train and evaluate a model:

   ```powershell
   python -m backend.models.train_fare_model path\to\labeled-fares.csv
   ```

   The command prints holdout MAE/RMSE and writes `backend/models/fare_model.joblib`. You can provide `--output path\to\model.joblib` to select another artifact path. Training data is not included; the schema file is intentionally header-only. The generated joblib file is ignored by Git and must be treated as a trusted local artifact.

The model uses one-hot encoded provider, vehicle, time-of-day, and currency features and imputed numeric route features. A model only predicts categories represented in its training data; unsupported categories use the existing rate card when one exists. Model output is a historical-data prediction, not a provider quote, live availability signal, or guaranteed price. Holdout metrics are meaningful only when the labeled dataset is representative and sufficiently large; the five-row minimum is a basic execution guard, not a quality threshold.

The Rapido and Namma Yatri rate cards in `backend/providers/rates.py` are approximate values used only for labelled INR estimates. They are not provider-supplied prices; update them only from reliable current rate information. Estimates use route distance and duration and can differ from actual fares due to city rates, demand, surge, traffic, tolls, and other provider rules. API, model, and route estimates do not guarantee ride availability.

## Verification

From the workspace root:

```powershell
python -m unittest cabcompare.backend.tests.test_comparison cabcompare.backend.tests.test_api cabcompare.backend.tests.test_fares cabcompare.backend.tests.test_routing -v
```

From `cabcompare/frontend`, after installing Node dependencies:

```powershell
npm run build
```

Screenshot checklist: desktop initial search view; mobile initial search view; desktop and mobile results with category/sort controls; location permission denied; API unavailable/error state; empty category state.

## Not Yet Implemented

This is a working comparison prototype, not a complete production platform. MySQL persistence, registration/login, authorized search history, favorites, savings analytics and Recharts dashboards, and authorized Namma Yatri network integration are not wired yet.

## v2 Update: Google Maps places and booking links

**Google Maps (location search + "use my location").** Create a key in Google Cloud Console, enable *Maps JavaScript API*, *Places API (New)* and *Geocoding API*, restrict it to HTTP referrers (your site origins), and set `VITE_GOOGLE_MAPS_API_KEY` in `frontend/.env`. Restart `npm run dev`. Without a key the app still works with typed text, and the locate button shows coordinates. Geolocation needs `localhost` or HTTPS.

**Booking links.** The "Book on ..." button opens the provider URL via `backend/providers/links.py`. Uber and Ola builder URLs include the selected pickup/drop coordinates when available. Rapido's existing generic URL only prefills if `RAPIDO_LINK_TEMPLATE` is configured; otherwise it opens the provider homepage. Namma Yatri's existing link opens its homepage and does not prefill the route. These URLs have only been checked in code here, not opened in a provider app/device. The API accepts optional `pickup_coords` / `destination_coords` and returns `booking` and `booking_url` on every ride.

**Fare retrieval.** Uber and Ola estimates are fetched server-side only when configured; if no valid API quote is available, the frontend shows the clearly labelled route-based rate-card estimates described above when route metrics exist. Rapido and Namma Yatri use model predictions when covered, otherwise the route-based rate-card estimates. All amounts are labelled by source; API estimates are not availability guarantees, model predictions are not live quotes, and route-card prices are not provider quotes.

## v3 Update: pre-filled Uber and Ola links

`backend/providers/links.py` retains the existing booking URL generation. Uber and Ola include route details when the selected locations have coordinates. Rapido and Namma Yatri remain as currently implemented; see the booking-links section above for their prefill limitations.
