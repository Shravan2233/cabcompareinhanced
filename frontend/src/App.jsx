import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import {
  ArrowDownUp, ArrowRight, Bike, CarFront, Check, ChevronDown, Clock3,
  Crosshair, ExternalLink, MapPin, Navigation, RefreshCw, ShieldCheck, Sparkles,
  TrainFront, TriangleAlert, Zap,
} from 'lucide-react'
import LocationInput from './LocationInput.jsx'
import { mapsEnabled, reverseGeocode, routeMetrics } from './maps.js'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000'
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
const hasCoords = (p) => p.lat != null && p.lng != null
const asPlace = (p) => (typeof p === 'string' ? place(p) : p)
const normalizeRoute = (r) => ({ pickup: asPlace(r.pickup), destination: asPlace(r.destination) })
const formatFare = (value) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)

function fareLabel(ride) {
  if (ride.fare_status === 'estimated') return 'ESTIMATED FARE'
  if (ride.fare_status === 'model') return 'MODEL ESTIMATE'
  if (ride.fare_status === 'live') return 'PROVIDER API ESTIMATE'
  return 'UNAVAILABLE'
}

function fareText(ride) {
  if (ride.fare_status === 'unavailable' || ride.fare == null || !ride.currency) return 'Fare unavailable'
  const low = ride.fare_low ?? ride.fare
  const high = ride.fare_high ?? ride.fare
  if (low !== high) return `${ride.currency} ${formatFare(low)}–${formatFare(high)}`
  return `${ride.currency} ${formatFare(ride.fare)}`
}

function fareDisclaimer(ride) {
  if (ride.fare_status === 'unavailable') return ride.fare_unavailable_reason
  return [ride.fare_disclaimer, ride.fare_estimate_note].filter(Boolean).join(' ')
}

function App() {
  const [pickup, setPickup] = useState(place(''))
  const [destination, setDestination] = useState(place(''))
  const [route, setRoute] = useState(null)
  const [rides, setRides] = useState([])
  const [category, setCategory] = useState('all')
  const [sort, setSort] = useState('cheapest')
  const [loading, setLoading] = useState(false)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [metrics, setMetrics] = useState(null)
  const [notice, setNotice] = useState('')
  const destinationRef = useRef(null)
  const resultsRef = useRef(null)
  const [recent, setRecent] = useState(() => {
    try { return JSON.parse(localStorage.getItem('cabcompare-recent') || '[]').map(normalizeRoute) } catch { return [] }
  })

  async function search(nextRoute, nextCategory = category, nextSort = sort, { scroll = false } = {}) {
    setLoading(true)
    setError('')
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
      setMetrics(response.data.route_metrics || null)
      setNotice(response.data.notice || 'Live provider fares are unavailable.')
      setRoute(nextRoute)
      setPickup(nextRoute.pickup)
      setDestination(nextRoute.destination)
      setRides(response.data.rides)
      setUpdatedAt(response.data.last_updated)
      setRecent((current) => {
        const same = (a, b) => a.pickup.text === b.pickup.text && a.destination.text === b.destination.text
        const updated = [nextRoute, ...current.filter((item) => !same(item, nextRoute))].slice(0, 4)
        try { localStorage.setItem('cabcompare-recent', JSON.stringify(updated)) } catch { /* storage unavailable */ }
        return updated
      })
      if (scroll) setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not load comparisons. Check that the CabCompare API is running and try again.')
      setRides([])
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
    setPickup(destination)
    setDestination(pickup)
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setError('Location is not available in this browser. You can enter your pickup manually.')
      return
    }
    setError('')
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const { latitude: lat, longitude: lng } = coords
        let text = `Current location (${lat.toFixed(4)}, ${lng.toFixed(4)})`
        if (mapsEnabled) { try { text = await reverseGeocode(lat, lng) } catch { /* keep coordinates as the label */ } }
        setPickup({ text, lat, lng })
        setLocating(false)
        destinationRef.current?.focus()
      },
      (failure) => {
        setLocating(false)
        setError(failure.code === 1
          ? 'Location permission was blocked. Allow it in your browser settings, or type your pickup instead.'
          : 'We could not find your location. Check GPS/network, or type your pickup instead.')
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
    )
  }

  const formattedTime = updatedAt ? new Date(updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''

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
        <span className="demo-pill"><span /> Hybrid fare estimates</span>
      </header>

      <main id="top">
        <section className="hero-grid" id="compare">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> THE SMARTER WAY TO GET THERE</div>
            <h1>Compare rides.<br /><span>Save more.</span></h1>
            <p className="hero-subtitle">One route, more choices. See ride options side by side before you book.</p>
            <div className="trust-row"><ShieldCheck size={16} /><span>Booking stays with your ride provider</span></div>
          </div>

          <form className="search-panel" onSubmit={handleSubmit}>
            <div className="panel-heading">
              <div><span className="panel-kicker">PLAN YOUR RIDE</span><h2>Where are you headed?</h2></div>
              <span className="route-icon"><Navigation size={19} /></span>
            </div>
            <div className="location-fields">
              <LocationInput kicker="FROM" label="Pickup location" dotClass="pickup-dot" value={pickup} placeholder="Pickup location"
                onTyping={(text) => setPickup(place(text))} onPick={setPickup}>
                <button className="icon-button locate-button" type="button" onClick={useCurrentLocation} disabled={locating} title="Use my current location" aria-label="Use my current location">
                  {locating ? <span className="button-spinner dark" /> : <Crosshair size={17} />}
                </button>
              </LocationInput>
              <button className="swap-button" type="button" onClick={swapLocations} title="Swap pickup and destination" aria-label="Swap pickup and destination"><ArrowDownUp size={15} /></button>
              <LocationInput kicker="TO" label="Destination" dotClass="destination-dot" value={destination} placeholder="Where to?" inputRef={destinationRef}
                onTyping={(text) => setDestination(place(text))} onPick={setDestination} />
            </div>
            <button className="search-button" type="submit" disabled={loading}>
              {loading ? <><span className="button-spinner" /> Comparing rides</> : <>Compare rides <ArrowRight size={17} /></>}
            </button>
            {error && <div className="error-message" role="alert"><TriangleAlert size={16} />{error}</div>}
            <div className="form-footnote"><span className="privacy-dot" /> {mapsEnabled ? 'Suggestions by Google Maps. ' : 'Type an area or landmark. '}Your route is only used to compare this trip</div>
          </form>
        </section>

        {route || loading ? (
          <section className="results-section" aria-live="polite" ref={resultsRef}>
            <div className="results-topline">
              <div>
                <div className="section-overline">YOUR ROUTE</div>
                {route
                  ? <div className="route-summary"><span>{route.pickup.text}</span><ArrowRight size={16} /><span>{route.destination.text}</span></div>
                  : <div className="route-summary">Fetching provider fares and route estimates…</div>}
              </div>
              <button type="button" className="refresh-button" onClick={() => search(route)} disabled={loading}>
                <RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh prices
              </button>
            </div>
            <div className="results-toolbar">
              <div className="category-tabs" role="tablist" aria-label="Filter by ride category">
                {CATEGORIES.map(({ id, label, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={category === id} className={category === id ? 'category-tab selected' : 'category-tab'} onClick={() => setCategory(id)}><Icon size={16} />{label}</button>)}
              </div>
              <label className="sort-control"><span>Sort by</span><select value={sort} onChange={(event) => setSort(event.target.value)}>{SORTS.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select><ChevronDown size={14} /></label>
            </div>
            <div className="results-meta"><span>{loading && !route ? 'Loading fare results…' : `${rides.length} options to compare${metrics ? ` · ${metrics.distance_km} km · about ${metrics.duration_minutes} min drive` : ''}`}</span><span className="updated-label"><Clock3 size={13} /> Updated {formattedTime || 'just now'}</span></div>
            {loading ? <div className="ride-list" aria-label="Loading ride options">{[1, 2, 3, 4, 5].map((item) => <div className="skeleton-card" key={item}><span /><div><i /><i /></div><i /><span /></div>)}</div> : rides.length ? (
              <div className="ride-list">
                {rides.map((ride) => <article className={ride.is_lowest ? 'ride-card lowest-card' : 'ride-card'} key={ride.id}>
                  <div className={`provider-symbol ${ride.ride_type}`} aria-hidden="true">{ride.ride_type === 'bike' ? <Bike size={20} /> : ride.ride_type === 'auto' ? <Navigation size={19} /> : <CarFront size={20} />}</div>
                  <div className="ride-main">
                    <div className="ride-title-row"><h3>{ride.provider}</h3>{ride.is_lowest && <span className="lowest-badge"><Check size={12} /> Lowest price</span>}</div>
                    <div className="ride-details"><span>{ride.product_name || ride.ride_type}</span></div>
                    <div className={`fare-source ${ride.fare_status}`}><span className={`fare-tag ${ride.fare_status}`}>{fareLabel(ride)}</span><span>{fareDisclaimer(ride)}</span></div>
                  </div>
                  <div className="ride-price" aria-label={`${ride.provider} ${fareText(ride)}`}><strong>{fareText(ride)}</strong><span>{ride.fare_status === 'estimated' ? 'Rate-card range · confirm in app' : ride.fare_status === 'model' ? 'Model prediction · confirm in app' : ride.fare_status === 'live' ? 'Provider API estimate · confirm in app' : 'Check fare in the provider app'}</span></div>
                  <div className="ride-action">
                    <a className="provider-button" href={ride.booking?.url} target="_blank" rel="noopener noreferrer">Book on {ride.provider} <ExternalLink size={14} /></a>
                    <span>{ride.booking?.prefilled ? 'Your route is pre-filled' : `Opens ${ride.provider} — enter your route there`}</span>
                  </div>
                </article>)}
              </div>
            ) : <div className="empty-state"><MapPin size={21} /><strong>No ride options in this category</strong><span>Try another ride type or compare all rides.</span></div>}
            <div className="fare-disclaimer"><TriangleAlert size={16} /><span>{notice || 'Live provider fares and availability are unavailable. Confirm the fare in the provider app before booking.'}</span></div>
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
            <div className="how-step"><span className="step-number">01</span><div><h3>Enter your route</h3><p>Tell us where your trip starts and ends.</p></div></div>
            <div className="step-rule" />
            <div className="how-step"><span className="step-number">02</span><div><h3>Compare your options</h3><p>Review providers and ride types before booking.</p></div></div>
            <div className="step-rule" />
            <div className="how-step"><span className="step-number">03</span><div><h3>Book with the provider</h3><p>Choose your ride in the provider's own app.</p></div></div>
          </div>
        </section>
      </main>

      <footer className="footer"><a className="brand footer-brand" href="#top"><span className="brand-mark"><ArrowDownUp size={16} strokeWidth={2.8} /></span><span>cab<span>compare</span></span></a><span>Independent comparisons. Provider-led bookings.</span><span className="footer-status"><Zap size={13} /> Live fares not connected</span></footer>
    </div>
  )
}

export default App