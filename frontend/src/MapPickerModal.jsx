import { useEffect, useRef, useState } from 'react'
import { AttributionControl, LngLatBounds, Map as MapLibreMap, Marker, NavigationControl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { ArrowRight, Check, MapPin, X } from 'lucide-react'
import { reverseGeocode } from './maps.js'

const OPENFREEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'

const QUICK_CITIES = [
  { label: 'Bengaluru', lng: 77.5946, lat: 12.9716 },
  { label: 'Mumbai', lng: 72.8777, lat: 19.0760 },
  { label: 'Delhi', lng: 77.2090, lat: 28.6139 },
  { label: 'Hyderabad', lng: 78.4867, lat: 17.3850 },
  { label: 'Chennai', lng: 80.2707, lat: 13.0827 },
]

const hasCoords = (p) => p?.lat != null && p?.lng != null

function makePinElement(kind) {
  const el = document.createElement('div')
  el.className = `map-pin ${kind} draggable`
  return el
}

export default function MapPickerModal({
  open, initialTarget = 'pickup', pickup, destination, onClose, onApply,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef({ pickup: null, destination: null })
  const targetRef = useRef(initialTarget)
  const reqIdRef = useRef(0)

  const [target, setTarget] = useState(initialTarget)
  const [draftPickup, setDraftPickup] = useState(pickup)
  const [draftDest, setDraftDest] = useState(destination)
  const [resolving, setResolving] = useState('')
  const [mapError, setMapError] = useState(false)

  useEffect(() => { targetRef.current = target }, [target])

  useEffect(() => {
    if (!open) return undefined
    setTarget(initialTarget)
    setDraftPickup(pickup)
    setDraftDest(destination)
    setResolving('')
    setMapError(false)

    const onKey = (event) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, initialTarget])

  async function updatePoint(which, lat, lng) {
    const fallback = `${lat.toFixed(4)}, ${lng.toFixed(4)}`
    const setter = which === 'pickup' ? setDraftPickup : setDraftDest
    setter((prev) => ({ text: prev?.text || fallback, lat, lng }))
    setResolving(which)
    const token = ++reqIdRef.current
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

  useEffect(() => {
    if (!open || !containerRef.current) return undefined

    let center = [77.5946, 12.9716]
    let zoom = 11
    if (hasCoords(pickup) && hasCoords(destination)) {
      center = [(pickup.lng + destination.lng) / 2, (pickup.lat + destination.lat) / 2]
      zoom = 12
    } else if (hasCoords(pickup)) {
      center = [pickup.lng, pickup.lat]
      zoom = 13
    } else if (hasCoords(destination)) {
      center = [destination.lng, destination.lat]
      zoom = 13
    }

    let map
    try {
      map = new MapLibreMap({
        container: containerRef.current,
        style: OPENFREEMAP_STYLE,
        center,
        zoom,
        attributionControl: false,
      })
    } catch {
      setMapError(true)
      return undefined
    }

    mapRef.current = map
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new AttributionControl({ compact: true }), 'bottom-right')
    map.getCanvas().style.cursor = 'crosshair'

    map.on('error', () => {
      if (!map.isStyleLoaded()) setMapError(true)
    })

    map.on('load', () => {
      const initialCoords = hasCoords(pickup) && hasCoords(destination)
        ? [[pickup.lng, pickup.lat], [destination.lng, destination.lat]]
        : []
      map.addSource('picker-line', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: initialCoords } },
      })
      map.addLayer({
        id: 'picker-line-layer',
        type: 'line',
        source: 'picker-line',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#087e68', 'line-width': 3, 'line-dasharray': [2, 2], 'line-opacity': 0.85 },
      })

      if (hasCoords(pickup) && hasCoords(destination)) {
        const bounds = new LngLatBounds([pickup.lng, pickup.lat], [pickup.lng, pickup.lat])
        bounds.extend([destination.lng, destination.lat])
        map.fitBounds(bounds, { padding: 64, maxZoom: 15, duration: 0 })
      }
    })

    map.on('click', (event) => {
      const { lat, lng } = event.lngLat
      updatePoint(targetRef.current, Number(lat.toFixed(6)), Number(lng.toFixed(6)))
    })

    return () => {
      markersRef.current.pickup?.remove()
      markersRef.current.destination?.remove()
      markersRef.current = { pickup: null, destination: null }
      mapRef.current = null
      map.remove()
    }
  }, [open])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const syncMarker = (which, point) => {
      const existing = markersRef.current[which]
      if (!hasCoords(point)) {
        if (existing) {
          existing.remove()
          markersRef.current[which] = null
        }
        return
      }
      if (existing) {
        existing.setLngLat([point.lng, point.lat])
      } else {
        const marker = new Marker({ element: makePinElement(which), draggable: true })
          .setLngLat([point.lng, point.lat])
          .addTo(map)
        marker.on('dragend', () => {
          const pos = marker.getLngLat()
          updatePoint(which, Number(pos.lat.toFixed(6)), Number(pos.lng.toFixed(6)))
        })
        markersRef.current[which] = marker
      }
    }

    syncMarker('pickup', draftPickup)
    syncMarker('destination', draftDest)

    const source = map.getSource?.('picker-line')
    if (source) {
      const coords = hasCoords(draftPickup) && hasCoords(draftDest)
        ? [[draftPickup.lng, draftPickup.lat], [draftDest.lng, draftDest.lat]]
        : []
      source.setData({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } })
    }
  }, [draftPickup, draftDest])

  if (!open) return null

  const canCompare = Boolean(draftPickup?.text?.trim() && draftDest?.text?.trim())

  return (
    <div className="map-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="map-picker-title" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="map-modal">
        <div className="map-modal-header">
          <div>
            <span className="panel-kicker">PIN ON MAP</span>
            <h2 id="map-picker-title">Click map or drag pins to set route</h2>
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
              onClick={() => setTarget('pickup')}
            >
              <span className="legend-dot pickup" /> Pin Pickup
            </button>
            <button
              type="button" role="tab" aria-selected={target === 'destination'}
              className={target === 'destination' ? 'picker-tab active' : 'picker-tab'}
              onClick={() => setTarget('destination')}
            >
              <span className="legend-dot destination" /> Pin Destination
            </button>
          </div>
          <div className="city-jumps" aria-label="Jump to city">
            {QUICK_CITIES.map((city) => (
              <button
                key={city.label} type="button" className="city-chip"
                onClick={() => mapRef.current?.flyTo({ center: [city.lng, city.lat], zoom: 12 })}
              >
                {city.label}
              </button>
            ))}
          </div>
        </div>

        {mapError ? (
          <div className="route-map-fallback picker-fallback">
            <MapPin size={18} />
            <div>
              <strong>Interactive map could not load</strong>
              <span>Close this dialog and type your pickup or destination instead.</span>
            </div>
          </div>
        ) : (
          <div className="map-picker-canvas" ref={containerRef} />
        )}

        <div className="map-modal-summary">
          <button type="button" className={target === 'pickup' ? 'summary-point active' : 'summary-point'} onClick={() => setTarget('pickup')}>
            <span className="legend-dot pickup" />
            <div>
              <small>PICKUP</small>
              <strong>
                {resolving === 'pickup'
                  ? 'Resolving address…'
                  : draftPickup?.text || 'Click on map to pin pickup'}
              </strong>
            </div>
          </button>
          <button type="button" className={target === 'destination' ? 'summary-point active' : 'summary-point'} onClick={() => setTarget('destination')}>
            <span className="legend-dot destination" />
            <div>
              <small>DESTINATION</small>
              <strong>
                {resolving === 'destination'
                  ? 'Resolving address…'
                  : draftDest?.text || 'Click on map to pin destination'}
              </strong>
            </div>
          </button>
        </div>

        <div className="map-modal-footer">
          <button type="button" className="secondary-button" onClick={() => onApply(draftPickup, draftDest, false)}>
            <Check size={15} /> Apply pins
          </button>
          <button
            type="button" className="primary-modal-button" disabled={!canCompare}
            onClick={() => onApply(draftPickup, draftDest, true)}
          >
            Compare rides <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
