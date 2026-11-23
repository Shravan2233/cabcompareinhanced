import { useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import {
  ArrowDownUp, ArrowRight, Bike, CarFront, Check, ChevronDown, Clock3,
  Copy, Crosshair, ExternalLink, Map, MapPin, Navigation, RefreshCw, ShieldCheck, Sparkles,
  TrainFront, TriangleAlert, X, Zap,
} from 'lucide-react'
import LocationInput from './LocationInput.jsx'
import MapPickerModal from './MapPickerModal.jsx'
import RouteMap from './RouteMap.jsx'
import { API_BASE, mapsEnabled, reverseGeocode, routeMetrics } from './maps.js'

const ROUTES = [
  ['Indiranagar, Bengaluru', 'MG Road, Bengaluru'],
  ['Bandra, Mumbai', 'Lower Parel, Mumbai'],
  ['Connaught Place, Delhi', 'Hauz Khas, Delhi'],
]
const CATEGORIES = [
  { id: 'all', label: 'All rides', icon: Sparkles },
  { id: 'bike', label: 'Bike', icon: Bike },
  { id: 'auto', label: 'Auto', icon: Navigation },
  { id: 'sedan', label: 'Sedan', icon: CarFront },
  { id: 'premium', label: 'Premium', icon: TrainFront },
]
const SORTS = [
  { id: 'cheapest', label: 'Cheapest' },
  { id: 'pickup', label: 'Fastest pickup' },
  { id: 'best_value', label: 'Best value' },
]

const place = (text) => ({ text })
const hasCoords = (p) => p?.lat != null && p?.lng != null
const asPlace = (p) => (typeof p === 'string' ? place(p) : p)
const normalizeRoute = (r) => ({ pickup: asPlace(r.pickup), destination: asPlace(r.destination) })
const formatFare = (value) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
const routeKey = (r) => (r ? `${r.pickup.text.trim().toLowerCase()}->${r.destination.text.trim().toLowerCase()}` : '')

function quoteKind(ride) {
  if (ride.quoteType) return ride.quoteType
  if (ride.fare_status === 'live') return 'LIVE_QUOTE'
  if (ride.fare_status === 'estimated') return 'FARE_ESTIMATE'
  return 'UNAVAILABLE'
}

function fareLabel(ride) {
  const kind = quoteKind(ride)
  if (kind === 'LIVE_QUOTE') return 'LIVE QUOTE'
  if (kind === 'FARE_ESTIMATE') {
    return ride.quoteSource === 'rate_card' ? 'ESTIMATED FARE' : 'PROVIDER ESTIMATE'
  }
  return 'UNAVAILABLE'
}

function fareTagClass(ride) {
  const kind = quoteKind(ride)
  if (kind === 'LIVE_QUOTE') return 'live'
  if (kind === 'FARE_ESTIMATE') return 'estimated'
  return 'unavailable'
}

function fareText(ride) {
  const kind = quoteKind(ride)
  if (kind === 'UNAVAILABLE' || ride.fare == null || !ride.currency) return 'Unavailable'
  const low = ride.fareRange?.min ?? ride.fare_low ?? ride.fare
  const high = ride.fareRange?.max ?? ride.fare_high ?? ride.fare
  if (low !== high) return `${ride.currency} ${formatFare(low)}–${formatFare(high)}`
  return `${ride.currency} ${formatFare(ride.fare)}`
}

function fareSubtitle(ride) {
  const kind = quoteKind(ride)
  if (kind === 'LIVE_QUOTE') return 'Actual provider quote'
  if (kind === 'FARE_ESTIMATE') {
    return ride.quoteSource === 'rate_card' ? 'City tariff estimate · confirm in app' : 'Provider estimate range'
  }
  return 'Check price in provider app'
}

function fareDetailsCopy(ride) {
  if (quoteKind(ride) === 'UNAVAILABLE') {
    return ride.error || ride.fare_unavailable_reason || 'No genuine provider quote returned.'
  }
  return ride.fare_disclaimer || 'Confirm final fare in the provider app before booking.'
}

function formatClockTime(isoString) {
  if (!isoString) return ''
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

function loadSavedUserFares() {
  try {
    return JSON.parse(localStorage.getItem('cabcompare-user-fares') || '{}')
  } catch {
    return {}
  }
}

function App() {
  const [pickup, setPickup] = useState(place(''))
  const [destination, setDestination] = useState(place(''))
  const [route, setRoute] = useState(null)
  const [rides, setRides] = useState([])
  const [cheapestQuote, setCheapestQuote] = useState(null)
  const [category, setCategory] = useState('all')
  const [sort, setSort] = useState('cheapest')
  const [loading, setLoading] = useState(false)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [metrics, setMetrics] = useState(null)
  const [routeCoords, setRouteCoords] = useState(null)
  const [routeGeometry, setRouteGeometry] = useState(null)
  const [notice, setNotice] = useState('')
  const [copiedId, setCopiedId] = useState('')
  const [mapPicker, setMapPicker] = useState({ open: false, target: 'pickup' })
  const [userFares, setUserFares] = useState(loadSavedUserFares)
  const [editingFareId, setEditingFareId] = useState('')
  const [fareDraft, setFareDraft] = useState('')
  const pickupEditedRef = useRef(false)
  const destinationRef = useRef(null)
  const resultsRef = useRef(null)
  const [recent, setRecent] = useState(() => {
    try { return JSON.parse(localStorage.getItem('cabcompare-recent') || '[]').map(normalizeRoute) } catch { return [] }
  })

  // Auto-populate current location in source field on initial open when browser permits.
  useEffect(() => {
    if (!navigator.geolocation || !window.isSecureContext) return undefined
    let cancelled = false
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        if (cancelled || pickupEditedRef.current) {
          setLocating(false)
          return
        }
        const { latitude: lat, longitude: lng } = coords
        let text = `Current location (${lat.toFixed(4)}, ${lng.toFixed(4)})`
        try { text = await reverseGeocode(lat, lng) } catch { /* keep coordinates as label */ }
        if (!cancelled && !pickupEditedRef.current) {
          setPickup({ text, lat, lng })
        }
        if (!cancelled) setLocating(false)
      },
      () => {
        if (!cancelled) setLocating(false)
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 },
    )
    return () => { cancelled = true }
  }, [])

  async function search(nextRoute, nextCategory = category, nextSort = sort, { scroll = false } = {}) {
    pickupEditedRef.current = true
    setLoading(true)
    setError('')
    setEditingFareId('')
    try {
      const body = { pickup: nextRoute.pickup.text, destination: nextRoute.destination.text, category: nextCategory, sort: nextSort }
      if (hasCoords(nextRoute.pickup)) body.pickup_coords = { lat: nextRoute.pickup.lat, lng: nextRoute.pickup.lng }
      if (hasCoords(nextRoute.destination)) body.destination_coords = { lat: nextRoute.destination.lat, lng: nextRoute.destination.lng }
      let gotMetrics = null
      if (mapsEnabled) {
        try { gotMetrics = await routeMetrics(nextRoute.pickup, nextRoute.destination) } catch { /* route metadata is optional */ }
        if (gotMetrics) body.route_metrics = gotMetrics
      }
      const response = await axios.post(`${API_BASE}/api/rides/compare`, body)
      const resolvedCoords = response.data.route_coords || null
      const syncedPickup = resolvedCoords?.pickup ? { ...nextRoute.pickup, ...resolvedCoords.pickup } : nextRoute.pickup
      const syncedDestination = resolvedCoords?.destination ? { ...nextRoute.destination, ...resolvedCoords.destination } : nextRoute.destination
      const syncedRoute = { pickup: syncedPickup, destination: syncedDestination }

      setMetrics(response.data.route_metrics || null)
      setRouteCoords(resolvedCoords)
      setRouteGeometry(response.data.route_geometry || null)
      setNotice(response.data.notice || 'Live provider quotes require configured credentials or ONDC integration.')
      setRoute(syncedRoute)
      setPickup(syncedPickup)
      setDestination(syncedDestination)
      setRides(response.data.rides)
      setCheapestQuote(response.data.cheapest_quote || null)
      setUpdatedAt(response.data.last_updated)
      setRecent((current) => {
        const same = (a, b) => a.pickup.text === b.pickup.text && a.destination.text === b.destination.text
        const updated = [syncedRoute, ...current.filter((item) => !same(item, syncedRoute))].slice(0, 4)
        try { localStorage.setItem('cabcompare-recent', JSON.stringify(updated)) } catch { /* storage unavailable */ }
        return updated
      })
      if (scroll) setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not load comparisons. Check that the CabCompare API is running and try again.')
      setRides([])
      setCheapestQuote(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (route) search(route, category, sort)
  }, [category, sort])

  function handleSubmit(event) {
    event.preventDefault()
    if (!pickup.text.trim() || !destination.text.trim()) {
      setError(!pickup.text.trim() ? 'Enter a pickup location, or tap the locate button.' : 'Enter where you want to go.')
      return
    }
    search({ pickup, destination }, category, sort, { scroll: true })
  }

  function swapLocations() {
    pickupEditedRef.current = true
    setPickup(destination)
    setDestination(pickup)
  }

  function useCurrentLocation() {
    pickupEditedRef.current = true
    if (!navigator.geolocation) {
      setError('Location is not available in this browser. You can enter your pickup manually or pin it on the map.')
      return
    }
    if (!window.isSecureContext) {
      setError('GPS auto-detect requires localhost or HTTPS. Type your pickup or use Pin on map below.')
      return
    }
    setError('')
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const { latitude: lat, longitude: lng } = coords
        let text = `Current location (${lat.toFixed(4)}, ${lng.toFixed(4)})`
        try { text = await reverseGeocode(lat, lng) } catch { /* keep coordinates as the label */ }
        setPickup({ text, lat, lng })
        setLocating(false)
        destinationRef.current?.focus()
      },
      (failure) => {
        setLocating(false)
        setError(failure.code === 1
          ? 'Location permission was blocked. Allow it in your browser settings, type your pickup, or pin it on the map.'
          : 'We could not find your location. Type your pickup or pin it on the map instead.')
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
    )
  }

  function applyPinnedRoute(nextPickup, nextDestination, shouldCompare) {
    pickupEditedRef.current = true
    const finalPickup = nextPickup?.text ? nextPickup : pickup
    const finalDest = nextDestination?.text ? nextDestination : destination
    setPickup(finalPickup)
    setDestination(finalDest)
    setMapPicker({ open: false, target: 'pickup' })
    setError('')
    if (shouldCompare && finalPickup.text.trim() && finalDest.text.trim()) {
      search({ pickup: finalPickup, destination: finalDest }, category, sort, { scroll: true })
    }
  }

  async function copyRouteForRide(rideId) {
    if (!route?.pickup?.text || !route?.destination?.text) return
    const summary = `Pickup: ${route.pickup.text}\nDestination: ${route.destination.text}`
    let copied = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(summary)
        copied = true
      }
    } catch {
      copied = false
    }
    if (!copied) {
      try {
        const el = document.createElement('textarea')
        el.value = summary
        el.setAttribute('readonly', '')
        el.style.position = 'fixed'
        el.style.opacity = '0'
        document.body.appendChild(el)
        el.select()
        copied = document.execCommand('copy')
        document.body.removeChild(el)
      } catch {
        copied = false
      }
    }
    if (copied) {
      setCopiedId(rideId)
      setTimeout(() => setCopiedId((current) => (current === rideId ? '' : current)), 2400)
    }
  }

  const activeRouteKey = routeKey(route)
  const routeUserFares = useMemo(() => userFares[activeRouteKey] || {}, [userFares, activeRouteKey])

  function saveUserFare(ride) {
    const parsed = Number(fareDraft)
    if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 100000 || !activeRouteKey) return
    const next = {
      ...userFares,
      [activeRouteKey]: {
        ...(userFares[activeRouteKey] || {}),
        [ride.id]: {
          fare: Math.round(parsed * 100) / 100,
          provider: ride.provider,
          vehicleType: ride.vehicleType || ride.product_name || ride.ride_type,
          savedAt: new Date().toISOString(),
        },
      },
    }
    setUserFares(next)
    try { localStorage.setItem('cabcompare-user-fares', JSON.stringify(next)) } catch { /* ignore storage quota */ }
    setEditingFareId('')
    setFareDraft('')
  }

  function clearUserFare(rideId) {
    if (!activeRouteKey || !userFares[activeRouteKey]) return
    const routeEntries = { ...userFares[activeRouteKey] }
    delete routeEntries[rideId]
    const next = { ...userFares, [activeRouteKey]: routeEntries }
    setUserFares(next)
    try { localStorage.setItem('cabcompare-user-fares', JSON.stringify(next)) } catch { /* ignore storage quota */ }
  }

  const cheapestUserFare = useMemo(() => {
    const entries = Object.entries(routeUserFares)
    if (!entries.length) return null
    const [bestId, best] = entries.reduce((min, item) => (item[1].fare < min[1].fare ? item : min))
    return { id: bestId, ...best }
  }, [routeUserFares])

  const genuineCount = rides.filter((ride) => quoteKind(ride) !== 'UNAVAILABLE').length
  const formattedTime = formatClockTime(updatedAt)

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="CabCompare home">
          <span className="brand-mark"><ArrowDownUp size={19} strokeWidth={2.8} /></span>
          <span>cab<span>compare</span></span>
        </a>
        <nav className="nav-links" aria-label="Main navigation">
          <a className="nav-active" href="#compare">Compare</a>
          <a href="#how-it-works">How it works</a>
        </nav>
        <span className="demo-pill"><span /> OpenStreetMap · City rate cards</span>
      </header>

      <main id="top">
        <section className="hero-grid" id="compare">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> THE SMARTER WAY TO GET THERE</div>
            <h1>Compare rides.<br /><span>Save more.</span></h1>
            <p className="hero-subtitle">Compare city tariff estimates using OpenStreetMap road routes, then jump straight into Uber, Ola, Rapido, and Namma Yatri with prefilled pickup and drop.</p>
            <div className="trust-row"><ShieldCheck size={16} /><span>Transparent estimates · Booking stays with each provider</span></div>
          </div>

          <form className="search-panel" onSubmit={handleSubmit}>
            <div className="panel-heading">
              <div><span className="panel-kicker">PLAN YOUR RIDE</span><h2>Where are you headed?</h2></div>
              <span className="route-icon"><Navigation size={19} /></span>
            </div>
            <div className="location-fields">
              <LocationInput
                kicker="FROM" label="Pickup location" dotClass="pickup-dot" value={pickup}
                near={hasCoords(destination) ? destination : null}
                placeholder={locating ? 'Detecting your location…' : 'Type pickup area or landmark'}
                onTyping={(text) => { pickupEditedRef.current = true; setPickup(place(text)) }}
                onPick={(picked) => { pickupEditedRef.current = true; setPickup(picked) }}
              >
                <button className="icon-button locate-button" type="button" onClick={useCurrentLocation} disabled={locating} title="Use my current location" aria-label="Use my current location">
                  {locating ? <span className="button-spinner dark" /> : <Crosshair size={17} />}
                </button>
              </LocationInput>
              <button className="swap-button" type="button" onClick={swapLocations} title="Swap pickup and destination" aria-label="Swap pickup and destination"><ArrowDownUp size={15} /></button>
              <LocationInput
                kicker="TO" label="Destination" dotClass="destination-dot" value={destination}
                near={hasCoords(pickup) ? pickup : null}
                placeholder="Type destination area or landmark" inputRef={destinationRef}
                onTyping={(text) => setDestination(place(text))} onPick={setDestination}
              />
            </div>

            <div className="pin-bar">
              <span className="pin-bar-label"><Map size={14} /> Pin on map</span>
              <div className="pin-bar-actions">
                <button
                  type="button"
                  className={hasCoords(pickup) ? 'pin-chip pinned' : 'pin-chip'}
                  onClick={() => setMapPicker({ open: true, target: 'pickup' })}
                >
                  <span className="legend-dot pickup" /> Pickup
                </button>
                <button
                  type="button"
                  className={hasCoords(destination) ? 'pin-chip pinned' : 'pin-chip'}
                  onClick={() => setMapPicker({ open: true, target: 'destination' })}
                >
                  <span className="legend-dot destination" /> Destination
                </button>
              </div>
            </div>

            <button className="search-button" type="submit" disabled={loading}>
              {loading ? <><span className="button-spinner" /> Checking providers</> : <>Compare rides <ArrowRight size={17} /></>}
            </button>
            {error && <div className="error-message" role="alert"><TriangleAlert size={16} />{error}</div>}
            <div className="form-footnote"><span className="privacy-dot" /> {mapsEnabled ? 'Suggestions by Google Maps. ' : 'Free suggestions via OpenStreetMap. '}Enter text or pin locations on the map</div>
          </form>
        </section>

        {route || loading ? (
          <section className="results-section" aria-live="polite" ref={resultsRef}>
            <div className="results-topline">
              <div>
                <div className="section-overline">YOUR ROUTE</div>
                {route
                  ? <div className="route-summary"><span>{route.pickup.text}</span><ArrowRight size={16} /><span>{route.destination.text}</span></div>
                  : <div className="route-summary">Checking configured provider quotes and route distance…</div>}
              </div>
              <button type="button" className="refresh-button" onClick={() => search(route)} disabled={loading}>
                <RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh
              </button>
            </div>
            {!loading && route && (
              <RouteMap
                route={route} routeCoords={routeCoords} routeGeometry={routeGeometry} metrics={metrics}
                onAdjustPins={() => setMapPicker({ open: true, target: 'pickup' })}
              />
            )}
            <div className="results-toolbar">
              <div className="category-tabs" role="tablist" aria-label="Filter by ride category">
                {CATEGORIES.map(({ id, label, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={category === id} className={category === id ? 'category-tab selected' : 'category-tab'} onClick={() => setCategory(id)}><Icon size={16} />{label}</button>)}
              </div>
              <label className="sort-control"><span>Sort by</span><select value={sort} onChange={(event) => setSort(event.target.value)}>{SORTS.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select><ChevronDown size={14} /></label>
            </div>
            <div className="results-meta">
              <span className="tabular-figures">
                {loading && !route
                  ? 'Checking fares and route…'
                  : `${rides.length} options (${genuineCount} priced)${metrics ? ` · ${metrics.distance_km} km · ~${metrics.duration_minutes} min drive` : ''}`}
              </span>
              <span className="updated-label"><Clock3 size={13} /> Checked {formattedTime || 'just now'}</span>
            </div>

            {!loading && cheapestQuote && (
              <div className="cheapest-banner">
                <Check size={15} />
                <span>
                  {cheapestQuote.quoteType === 'LIVE_QUOTE' ? 'Cheapest live quote:' : cheapestQuote.quoteSource === 'rate_card' ? 'Lowest estimated ride:' : 'Cheapest provider estimate:'}{' '}
                  <strong>{cheapestQuote.provider} · {cheapestQuote.vehicleType}</strong> (
                  {cheapestQuote.fareRange && cheapestQuote.fareRange.min !== cheapestQuote.fareRange.max
                    ? `${cheapestQuote.currency} ${formatFare(cheapestQuote.fareRange.min)}–${formatFare(cheapestQuote.fareRange.max)}`
                    : `${cheapestQuote.currency} ${formatFare(cheapestQuote.fare)}`}
                  )
                </span>
              </div>
            )}

            {!loading && cheapestUserFare && (
              <div className="user-logged-banner">
                <span>
                  Cheapest fare you recorded for this route: <strong>{cheapestUserFare.provider} · {cheapestUserFare.vehicleType}</strong> — INR {formatFare(cheapestUserFare.fare)} (logged {formatClockTime(cheapestUserFare.savedAt)})
                </span>
              </div>
            )}

            {loading ? <div className="ride-list" aria-label="Loading ride options">{[1, 2, 3, 4, 5].map((item) => <div className="skeleton-card" key={item}><span /><div><i /><i /></div><i /><span /></div>)}</div> : rides.length ? (
              <div className="ride-list">
                {rides.map((ride) => {
                  const userEntry = routeUserFares[ride.id]
                  const isEditing = editingFareId === ride.id
                  const prefillsRoute = Boolean(ride.booking?.prefills_route ?? ride.booking?.prefilled)
                  const quoteClock = formatClockTime(ride.retrievedAt) || formattedTime
                  return (
                    <article className={ride.is_lowest ? 'ride-card lowest-card' : 'ride-card'} key={ride.id}>
                      <div className={`provider-symbol ${ride.ride_type}`} aria-hidden="true">{ride.ride_type === 'bike' ? <Bike size={20} /> : ride.ride_type === 'auto' ? <Navigation size={19} /> : <CarFront size={20} />}</div>
                      <div className="ride-main">
                        <div className="ride-title-row">
                          <h3>{ride.provider}</h3>
                          {ride.is_lowest && <span className="lowest-badge"><Check size={12} /> Cheapest quote</span>}
                          {userEntry && cheapestUserFare?.id === ride.id && Object.keys(routeUserFares).length > 1 && (
                            <span className="lowest-badge user-best">Lowest you logged</span>
                          )}
                        </div>
                        <div className="ride-details">
                          <span>{ride.vehicleType || ride.product_name || ride.ride_type}</span>
                          {(ride.etaMinutes ?? ride.pickup_eta_minutes) != null && (
                            <>
                              <span className="detail-separator" />
                              <span>Pickup ~{ride.etaMinutes ?? ride.pickup_eta_minutes} min</span>
                            </>
                          )}
                          {quoteClock && (
                            <>
                              <span className="detail-separator" />
                              <span>{quoteClock}</span>
                            </>
                          )}
                        </div>
                        <div className={`fare-source ${fareTagClass(ride)}`}>
                          <span className={`fare-tag ${fareTagClass(ride)}`}>{fareLabel(ride)}</span>
                          <span>{fareDetailsCopy(ride)}</span>
                        </div>
                      </div>
                      <div className="ride-price" aria-label={`${ride.provider} ${fareText(ride)}`}>
                        {userEntry ? (
                          <>
                            <strong className="tabular-figures user-fare-value">INR {formatFare(userEntry.fare)}</strong>
                            <span className="user-fare-meta">
                              USER ENTERED · {formatClockTime(userEntry.savedAt)}{' '}
                              <button type="button" className="inline-link-btn" onClick={() => clearUserFare(ride.id)}>Clear</button>
                            </span>
                            {quoteKind(ride) !== 'UNAVAILABLE' && (
                              <span className="user-fare-est">Est: {fareText(ride)}</span>
                            )}
                          </>
                        ) : (
                          <>
                            <strong className="tabular-figures">{fareText(ride)}</strong>
                            <span>{fareSubtitle(ride)}</span>
                          </>
                        )}
                        {isEditing ? (
                          <div className="log-fare-form">
                            <input
                              type="number"
                              min="1"
                              max="100000"
                              step="1"
                              placeholder="₹ fare"
                              value={fareDraft}
                              onChange={(event) => setFareDraft(event.target.value)}
                              aria-label={`Enter observed fare for ${ride.provider}`}
                            />
                            <button type="button" className="log-save-btn" onClick={() => saveUserFare(ride)}>Save</button>
                            <button type="button" className="log-cancel-btn" onClick={() => setEditingFareId('')} aria-label="Cancel"><X size={12} /></button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="inline-link-btn"
                            onClick={() => {
                              setEditingFareId(ride.id)
                              setFareDraft(userEntry ? String(userEntry.fare) : '')
                            }}
                          >
                            {userEntry ? 'Edit fare seen' : 'Log fare seen'}
                          </button>
                        )}
                      </div>
                      <div className="ride-action">
                        <div className="ride-action-buttons">
                          {!prefillsRoute && (
                            <button
                              type="button"
                              className="copy-route-button"
                              onClick={() => copyRouteForRide(ride.id)}
                              title="Copy pickup and destination to paste in app"
                              aria-label={`Copy route for ${ride.provider}`}
                            >
                              {copiedId === ride.id ? <Check size={13} /> : <Copy size={13} />}
                            </button>
                          )}
                          <a
                            className="provider-button"
                            href={ride.booking?.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={() => { if (!prefillsRoute) copyRouteForRide(ride.id) }}
                          >
                            Open {ride.provider} <ExternalLink size={14} />
                          </a>
                        </div>
                        <span>
                          {prefillsRoute
                            ? 'Pickup & drop prefilled'
                            : copiedId === ride.id
                              ? `Route copied — paste in ${ride.provider}`
                              : 'Opens home screen (copies route)'}
                        </span>
                      </div>
                    </article>
                  )
                })}
              </div>
            ) : <div className="empty-state"><MapPin size={21} /><strong>No ride options in this category</strong><span>Try another ride type or compare all rides.</span></div>}
            <div className="fare-disclaimer"><TriangleAlert size={16} /><span>{notice || 'Only genuine provider quotes are shown when authorized integrations are configured. Always confirm final fares inside each app.'}</span></div>
          </section>
        ) : (
          <section className="discovery-section">
            <div className="discovery-column">
              <div className="section-heading"><div><div className="section-overline">PICK UP WHERE YOU LEFT OFF</div><h2>Recent searches</h2></div><span className="small-caption">Saved on this device</span></div>
              {recent.length ? <div className="recent-list">{recent.map((item, index) => <button type="button" className="recent-route" key={`${item.pickup.text}-${index}`} onClick={() => search(item, category, sort, { scroll: true })}><span className="recent-route-icon"><Clock3 size={16} /></span><span className="recent-route-text"><strong>{item.pickup.text}</strong><span>{item.destination.text}</span></span><ArrowRight size={16} /></button>)}</div> : <p className="muted-copy">Your recent routes will show up here.</p>}
            </div>
            <div className="discovery-column popular-column">
              <div className="section-heading"><div><div className="section-overline">ROUTES TO EXPLORE</div><h2>Popular routes</h2></div><span className="sample-note">Sample routes</span></div>
              <div className="popular-list">{ROUTES.map(([from, to]) => <button type="button" className="popular-route" key={from} onClick={() => search({ pickup: place(from), destination: place(to) }, category, sort, { scroll: true })}><span className="popular-route-points"><span><i />{from}</span><span><i />{to}</span></span><span className="popular-route-action">Compare <ArrowRight size={14} /></span></button>)}</div>
            </div>
          </section>
        )}

        <section className="how-section" id="how-it-works">
          <div className="how-heading"><div className="section-overline">A BETTER WAY TO BOOK</div><h2>Three steps. Better choices.</h2></div>
          <div className="how-steps">
            <div className="how-step"><span className="step-number">01</span><div><h3>Enter your route</h3><p>Search OpenStreetMap or pin exact spots on the map.</p></div></div>
            <div className="step-rule" />
            <div className="how-step"><span className="step-number">02</span><div><h3>Compare estimates</h3><p>Review city rate-card fare ranges (or live quotes when connected) across categories.</p></div></div>
            <div className="step-rule" />
            <div className="how-step"><span className="step-number">03</span><div><h3>Open provider or log fare</h3><p>Jump straight into the app to confirm surge and book, or log actual fares seen.</p></div></div>
          </div>
        </section>
      </main>

      <footer className="footer"><a className="brand footer-brand" href="#top"><span className="brand-mark"><ArrowDownUp size={16} strokeWidth={2.8} /></span><span>cab<span>compare</span></span></a><span>Independent comparisons. Provider-led bookings.</span><span className="footer-status"><Zap size={13} /> OpenStreetMap routing · City tariff estimates</span></footer>

      <MapPickerModal
        open={mapPicker.open}
        initialTarget={mapPicker.target}
        pickup={pickup}
        destination={destination}
        onClose={() => setMapPicker((state) => ({ ...state, open: false }))}
        onApply={applyPinnedRoute}
      />
    </div>
  )
}

export default App
