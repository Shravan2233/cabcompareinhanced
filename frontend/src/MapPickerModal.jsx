import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { ArrowRight, Check, Crosshair, MapPin, Search, X } from 'lucide-react'
import { addFreeTileLayer, createPinIcon } from './leafletTiles.js'
import { placeCoordinates, reverseGeocode, suggestPlaces } from './maps.js'

const QUICK_CITIES = [
  { label: 'Bengaluru', lat: 12.9716, lng: 77.5946 },
  { label: 'Mumbai', lat: 19.0760, lng: 72.8777 },
  { label: 'Delhi', lat: 28.6139, lng: 77.2090 },
  { label: 'Hyderabad', lat: 17.3850, lng: 78.4867 },
  { label: 'Chennai', lat: 13.0827, lng: 80.2707 },
]

const hasCoords = (p) => p?.lat != null && p?.lng != null

export default function MapPickerModal({
  open, initialTarget = 'pickup', pickup, destination, onClose, onApply,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const otherMarkerRef = useRef(null)
  const lineRef = useRef(null)
  const targetRef = useRef(initialTarget)
  const programmaticMoveRef = useRef(false)
  const reqIdRef = useRef(0)
  const reverseTimerRef = useRef(null)
  const draftPickupRef = useRef(pickup)
  const draftDestRef = useRef(destination)

  const [target, setTarget] = useState(initialTarget)
  const [draftPickup, setDraftPickup] = useState(pickup)
  const [draftDest, setDraftDest] = useState(destination)
  const [resolving, setResolving] = useState('')
  const [isPanning, setIsPanning] = useState(false)
  const [locatingGps, setLocatingGps] = useState(false)
  const [mapNotice, setMapNotice] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchItems, setSearchItems] = useState([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchSearched, setSearchSearched] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [searchActive, setSearchActive] = useState(-1)

  useEffect(() => { targetRef.current = target }, [target])
  useEffect(() => { draftPickupRef.current = draftPickup }, [draftPickup])
  useEffect(() => { draftDestRef.current = draftDest }, [draftDest])

  useEffect(() => {
    if (!open) return undefined
    setTarget(initialTarget)
    targetRef.current = initialTarget
    setDraftPickup(pickup)
    draftPickupRef.current = pickup
    setDraftDest(destination)
    draftDestRef.current = destination
    setResolving('')
    setIsPanning(false)
    setLocatingGps(false)
    setMapNotice('')
    setSearchQuery('')
    setSearchItems([])
    setSearchOpen(false)
    setSearchSearched(false)
    setSearchError('')

    const onKey = (event) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, initialTarget])

  // Search places inside the map modal, biased toward the current map viewport center.
  useEffect(() => {
    if (!open || !searchOpen || searchQuery.trim().length < 2) {
      setSearchItems([])
      setSearchBusy(false)
      setSearchSearched(false)
      setSearchError('')
      return undefined
    }
    let cancelled = false
    setSearchBusy(true)
    setSearchError('')
    const timer = setTimeout(async () => {
      try {
        const center = mapRef.current?.getCenter?.()
        const bias = center ? { lat: center.lat, lng: center.lng } : null
        const found = await suggestPlaces(searchQuery.trim(), null, bias)
        if (!cancelled) {
          setSearchItems(found.slice(0, 6))
          setSearchActive(-1)
          setSearchSearched(true)
          setSearchError('')
        }
      } catch (err) {
        if (!cancelled) {
          setSearchItems([])
          setSearchSearched(true)
          setSearchError(err?.message || 'Unable to search places right now.')
        }
      } finally {
        if (!cancelled) setSearchBusy(false)
      }
    }, 220)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [open, searchOpen, searchQuery])

  function scheduleReverseGeocode(which, lat, lng, immediate = false) {
    const fallback = `${lat.toFixed(4)}, ${lng.toFixed(4)}`
    const setter = which === 'pickup' ? setDraftPickup : setDraftDest
    setter((prev) => ({
      text: prev?.text && !/^-?\d+\.\d+, -?\d+\.\d+$/.test(prev.text) ? prev.text : fallback,
      lat,
      lng,
    }))
    if (reverseTimerRef.current) clearTimeout(reverseTimerRef.current)
    const token = ++reqIdRef.current
    const run = async () => {
      setResolving(which)
      try {
        const label = await reverseGeocode(lat, lng)
        if (reqIdRef.current === token) {
          setter({ text: label || fallback, lat, lng })
        }
      } catch {
        if (reqIdRef.current === token) {
          setter({ text: fallback, lat, lng })
        }
      } finally {
        if (reqIdRef.current === token) setResolving('')
      }
    }
    if (immediate) {
      run()
    } else {
      reverseTimerRef.current = setTimeout(run, 260)
    }
  }

  function moveMapProgrammatically(lat, lng, zoom = 15) {
    const map = mapRef.current
    if (!map) return
    programmaticMoveRef.current = true
    map.setView([lat, lng], zoom, { animate: true })
  }

  function switchTarget(nextTarget) {
    setTarget(nextTarget)
    targetRef.current = nextTarget
    setSearchQuery('')
    setSearchItems([])
    setSearchOpen(false)
    setSearchSearched(false)
    setSearchError('')
    setSearchActive(-1)
    setMapNotice('')
    const point = nextTarget === 'pickup' ? draftPickupRef.current : draftDestRef.current
    if (hasCoords(point)) {
      moveMapProgrammatically(point.lat, point.lng, Math.max(mapRef.current?.getZoom?.() || 14, 15))
    }
  }

  function locateOnMap() {
    if (!navigator.geolocation) {
      setMapNotice('Location is not supported in this browser.')
      return
    }
    if (!window.isSecureContext) {
      setMapNotice('GPS button requires localhost or HTTPS. Drag map or search instead.')
      return
    }
    setMapNotice('')
    setLocatingGps(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const lat = Number(coords.latitude.toFixed(6))
        const lng = Number(coords.longitude.toFixed(6))
        setLocatingGps(false)
        moveMapProgrammatically(lat, lng, 16)
        scheduleReverseGeocode(targetRef.current, lat, lng, true)
      },
      () => {
        setLocatingGps(false)
        setMapNotice('Could not read GPS. Drag the map under the pin or use search.')
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    )
  }

  function onSearchKeyDown(event) {
    if (!searchOpen || !searchItems.length) return
    if (event.key === 'ArrowDown') { event.preventDefault(); setSearchActive((i) => (i + 1) % searchItems.length) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setSearchActive((i) => (i <= 0 ? searchItems.length - 1 : i - 1)) }
    else if (event.key === 'Enter' && searchActive >= 0) { event.preventDefault(); pickSearchResult(searchItems[searchActive]) }
    else if (event.key === 'Escape') { event.stopPropagation(); setSearchOpen(false) }
  }

  async function pickSearchResult(item) {
    setSearchOpen(false)
    setSearchItems([])
    setSearchQuery(item.main || item.text)
    setMapNotice('')
    try {
      const resolved = await placeCoordinates(item)
      const setter = targetRef.current === 'pickup' ? setDraftPickup : setDraftDest
      setter(resolved)
      if (resolved.lat != null && resolved.lng != null) {
        moveMapProgrammatically(resolved.lat, resolved.lng, 16)
      }
    } catch {
      /* ignore failed place lookup */
    }
  }

  function syncOtherMarkerAndLine(map) {
    const active = targetRef.current
    const otherPoint = active === 'pickup' ? draftDestRef.current : draftPickupRef.current
    const otherKind = active === 'pickup' ? 'destination' : 'pickup'

    if (otherMarkerRef.current) {
      otherMarkerRef.current.remove()
      otherMarkerRef.current = null
    }
    if (hasCoords(otherPoint)) {
      const marker = L.marker([otherPoint.lat, otherPoint.lng], {
        icon: createPinIcon(otherKind),
      }).addTo(map)
      marker.on('click', () => switchTarget(otherKind))
      otherMarkerRef.current = marker
    }

    if (lineRef.current) {
      const center = map.getCenter()
      if (hasCoords(otherPoint) && center) {
        lineRef.current.setLatLngs([[center.lat, center.lng], [otherPoint.lat, otherPoint.lng]])
      } else {
        lineRef.current.setLatLngs([])
      }
    }
  }

  useEffect(() => {
    if (!open || !containerRef.current) return undefined

    const activePoint = initialTarget === 'pickup' ? pickup : destination
    const fallbackPoint = initialTarget === 'pickup' ? destination : pickup
    let center = [12.9716, 77.5946]
    let zoom = 13
    if (hasCoords(activePoint)) {
      center = [activePoint.lat, activePoint.lng]
      zoom = 15
    } else if (hasCoords(fallbackPoint)) {
      center = [fallbackPoint.lat, fallbackPoint.lng]
      zoom = 14
    }

    const map = L.map(containerRef.current, {
      center,
      zoom,
      zoomControl: true,
      attributionControl: true,
    })
    mapRef.current = map
    addFreeTileLayer(map)

    lineRef.current = L.polyline([], {
      color: '#087e68',
      weight: 3,
      dashArray: '6 6',
      opacity: 0.85,
    }).addTo(map)

    syncOtherMarkerAndLine(map)

    map.on('movestart', () => {
      setIsPanning(true)
    })

    map.on('move', () => {
      const otherPoint = targetRef.current === 'pickup' ? draftDestRef.current : draftPickupRef.current
      if (lineRef.current) {
        if (hasCoords(otherPoint)) {
          const c = map.getCenter()
          lineRef.current.setLatLngs([[c.lat, c.lng], [otherPoint.lat, otherPoint.lng]])
        } else {
          lineRef.current.setLatLngs([])
        }
      }
    })

    map.on('moveend', () => {
      setIsPanning(false)
      if (programmaticMoveRef.current) {
        programmaticMoveRef.current = false
        return
      }
      const c = map.getCenter()
      const lat = Number(c.lat.toFixed(6))
      const lng = Number(c.lng.toFixed(6))
      scheduleReverseGeocode(targetRef.current, lat, lng, false)
    })

    map.on('click', (event) => {
      setSearchOpen(false)
      setMapNotice('')
      const lat = Number(event.latlng.lat.toFixed(6))
      const lng = Number(event.latlng.lng.toFixed(6))
      moveMapProgrammatically(lat, lng, Math.max(map.getZoom(), 15))
      scheduleReverseGeocode(targetRef.current, lat, lng, true)
    })

    const resizeTimer = setTimeout(() => map.invalidateSize(), 80)

    return () => {
      clearTimeout(resizeTimer)
      if (reverseTimerRef.current) clearTimeout(reverseTimerRef.current)
      otherMarkerRef.current?.remove()
      otherMarkerRef.current = null
      lineRef.current = null
      mapRef.current = null
      map.remove()
    }
  }, [open])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    syncOtherMarkerAndLine(map)
  }, [target, draftPickup, draftDest])

  function finalizeAndApply(shouldCompare) {
    let nextPickup = draftPickup
    let nextDest = draftDest
    const c = mapRef.current?.getCenter?.()
    if (c) {
      const centerLat = Number(c.lat.toFixed(6))
      const centerLng = Number(c.lng.toFixed(6))
      const centerLabel = `${centerLat.toFixed(4)}, ${centerLng.toFixed(4)}`
      if (target === 'pickup' && !hasCoords(nextPickup)) {
        nextPickup = { text: nextPickup?.text?.trim() || centerLabel, lat: centerLat, lng: centerLng }
      } else if (target === 'destination' && !hasCoords(nextDest)) {
        nextDest = { text: nextDest?.text?.trim() || centerLabel, lat: centerLat, lng: centerLng }
      }
    }
    onApply(nextPickup, nextDest, shouldCompare)
  }

  if (!open) return null

  const activePoint = target === 'pickup' ? draftPickup : draftDest
  const canCompare = Boolean(
    (draftPickup?.text?.trim() || target === 'pickup') &&
    (draftDest?.text?.trim() || target === 'destination'),
  )

  return (
    <div
      className="map-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="map-picker-title"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="map-modal">
        <div className="map-modal-header">
          <div>
            <span className="panel-kicker">OPENSTREETMAP PIN PICKER</span>
            <h2 id="map-picker-title">Move map to place pin</h2>
          </div>
          <button type="button" className="map-modal-close" onClick={onClose} aria-label="Close map picker">
            <X size={18} />
          </button>
        </div>

        <div className="map-modal-controls">
          <div className="picker-mode-tabs" role="tablist" aria-label="Select pin to place">
            <button
              type="button" role="tab" aria-selected={target === 'pickup'}
              className={target === 'pickup' ? 'picker-tab active' : 'picker-tab'}
              onClick={() => switchTarget('pickup')}
            >
              <span className="legend-dot pickup" /> Pin Pickup
            </button>
            <button
              type="button" role="tab" aria-selected={target === 'destination'}
              className={target === 'destination' ? 'picker-tab active' : 'picker-tab'}
              onClick={() => switchTarget('destination')}
            >
              <span className="legend-dot destination" /> Pin Destination
            </button>
          </div>
          <div className="city-jumps" aria-label="Jump to city">
            {QUICK_CITIES.map((city) => (
              <button
                key={city.label}
                type="button"
                className="city-chip"
                onClick={() => {
                  moveMapProgrammatically(city.lat, city.lng, 13)
                  scheduleReverseGeocode(targetRef.current, city.lat, city.lng, true)
                }}
              >
                {city.label}
              </button>
            ))}
          </div>
        </div>

        <div className="map-search-bar">
          <div className="map-search-input-wrap">
            <Search size={15} />
            <input
              type="text"
              value={searchQuery}
              placeholder={`Search ${target === 'pickup' ? 'pickup' : 'destination'} area or landmark…`}
              aria-label="Search place on map"
              onKeyDown={onSearchKeyDown}
              onFocus={() => setSearchOpen(true)}
              onChange={(e) => { setSearchQuery(e.target.value); setSearchOpen(true) }}
            />
            {searchQuery && (
              <button
                type="button"
                className="clear-button"
                aria-label="Clear map search"
                onClick={() => { setSearchQuery(''); setSearchItems([]); setSearchOpen(false) }}
              >
                <X size={13} />
              </button>
            )}
          </div>
          {searchOpen && (searchItems.length > 0 || searchBusy || searchSearched || searchError) && (
            <ul className="suggestions map-search-suggestions" role="listbox">
              {searchItems.map((item, index) => (
                <li
                  key={item.id}
                  role="option"
                  aria-selected={index === searchActive}
                  className={index === searchActive ? 'active' : ''}
                  onMouseEnter={() => setSearchActive(index)}
                  onMouseDown={(e) => { e.preventDefault(); pickSearchResult(item) }}
                >
                  <MapPin size={16} />
                  <span>
                    <strong>{item.main}</strong>
                    <small>{item.secondary}</small>
                  </span>
                </li>
              ))}
              {searchBusy && !searchItems.length && (
                <li className="suggestions-note">Searching OpenStreetMap…</li>
              )}
              {!searchBusy && searchError && (
                <li className="suggestions-note suggestions-error">{searchError}</li>
              )}
              {!searchBusy && !searchError && searchSearched && !searchItems.length && (
                <li className="suggestions-note">No matching places — drag map directly under pin</li>
              )}
            </ul>
          )}
        </div>

        <div className="map-picker-stage">
          <div className="map-picker-canvas" ref={containerRef} />

          {/* Fixed Uber/Ola-style center drop pin so mobile users simply pan the map */}
          <div className={`center-pin-overlay ${isPanning ? 'lifting' : ''}`} aria-hidden="true">
            <span className="center-pin-pill">
              {target === 'pickup' ? 'Pickup pin' : 'Drop pin'}
            </span>
            <svg width="38" height="48" viewBox="0 0 38 48" fill="none" className="center-pin-svg">
              <path
                d="M19 2C10.16 2 3 9.16 3 18c0 11.4 16 26 16 26s16-14.6 16-26C35 9.16 27.84 2 19 2Z"
                fill={target === 'pickup' ? '#087e68' : '#ed7659'}
                stroke="#ffffff"
                strokeWidth="3"
              />
              <circle cx="19" cy="17.5" r="6" fill="#ffffff" />
            </svg>
            <span className="center-pin-shadow" />
          </div>

          <button
            type="button"
            className="map-locate-fab"
            onClick={locateOnMap}
            disabled={locatingGps}
            title="Center pin on my GPS location"
            aria-label="Center pin on my GPS location"
          >
            {locatingGps ? <span className="button-spinner dark" /> : <Crosshair size={18} />}
          </button>

          {mapNotice && <div className="map-overlay-notice">{mapNotice}</div>}
        </div>

        <div className="map-modal-summary">
          <button
            type="button"
            className={target === 'pickup' ? 'summary-point active' : 'summary-point'}
            onClick={() => switchTarget('pickup')}
          >
            <span className="legend-dot pickup" />
            <div>
              <small>PICKUP PIN</small>
              <strong>
                {resolving === 'pickup'
                  ? 'Finding street / area…'
                  : draftPickup?.text || (hasCoords(activePoint) && target === 'pickup' ? 'Pinned on map' : 'Drag map to set pickup')}
              </strong>
            </div>
          </button>
          <button
            type="button"
            className={target === 'destination' ? 'summary-point active' : 'summary-point'}
            onClick={() => switchTarget('destination')}
          >
            <span className="legend-dot destination" />
            <div>
              <small>DESTINATION PIN</small>
              <strong>
                {resolving === 'destination'
                  ? 'Finding street / area…'
                  : draftDest?.text || 'Tap here & drag map for destination'}
              </strong>
            </div>
          </button>
        </div>

        <div className="map-modal-footer">
          <button type="button" className="secondary-button" onClick={() => finalizeAndApply(false)}>
            <Check size={15} /> Apply pins
          </button>
          <button
            type="button"
            className="primary-modal-button"
            disabled={!canCompare}
            onClick={() => finalizeAndApply(true)}
          >
            Compare rides <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
