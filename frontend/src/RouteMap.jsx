import { useEffect, useRef, useState } from 'react'
import { AttributionControl, LngLatBounds, Map as MapLibreMap, Marker, NavigationControl, Popup } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { LocateFixed, MapPin, Pencil } from 'lucide-react'

const OPENFREEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'

function makePinElement(kind) {
  const el = document.createElement('div')
  el.className = `map-pin ${kind}`
  return el
}

function routeBounds(points) {
  const bounds = new LngLatBounds()
  for (const [lng, lat] of points) bounds.extend([lng, lat])
  return bounds
}

export default function RouteMap({ route, routeCoords, routeGeometry, metrics, onAdjustPins = null }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const boundsRef = useRef(null)
  const [mapError, setMapError] = useState(false)

  const pickup = routeCoords?.pickup
  const destination = routeCoords?.destination
  const hasPins = pickup?.lat != null && pickup?.lng != null && destination?.lat != null && destination?.lng != null

  useEffect(() => {
    if (!hasPins || !containerRef.current) return undefined
    setMapError(false)

    const lineCoords = Array.isArray(routeGeometry) && routeGeometry.length >= 2
      ? routeGeometry
      : [[pickup.lng, pickup.lat], [destination.lng, destination.lat]]

    const bounds = routeBounds([...lineCoords, [pickup.lng, pickup.lat], [destination.lng, destination.lat]])
    boundsRef.current = bounds

    let map
    try {
      map = new MapLibreMap({
        container: containerRef.current,
        style: OPENFREEMAP_STYLE,
        bounds,
        fitBoundsOptions: { padding: 48, maxZoom: 15 },
        attributionControl: false,
      })
    } catch {
      setMapError(true)
      return undefined
    }

    mapRef.current = map
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new AttributionControl({ compact: true }), 'bottom-right')

    map.on('error', () => {
      // Only fall back if the base map itself failed to initialize a source
      if (!map.isStyleLoaded()) setMapError(true)
    })

    map.on('load', () => {
      if (!map.getSource('cabcompare-route')) {
        map.addSource('cabcompare-route', {
          type: 'geojson',
          data: {
            type: 'Feature',
            properties: {},
            geometry: { type: 'LineString', coordinates: lineCoords },
          },
        })
        map.addLayer({
          id: 'cabcompare-route-casing',
          type: 'line',
          source: 'cabcompare-route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': 7, 'line-opacity': 0.9 },
        })
        map.addLayer({
          id: 'cabcompare-route-line',
          type: 'line',
          source: 'cabcompare-route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#087e68', 'line-width': 4, 'line-opacity': 0.95 },
        })
      }

      new Marker({ element: makePinElement('pickup') })
        .setLngLat([pickup.lng, pickup.lat])
        .setPopup(new Popup({ offset: 14 }).setText(`Pickup: ${route?.pickup?.text || 'Start'}`))
        .addTo(map)

      new Marker({ element: makePinElement('destination') })
        .setLngLat([destination.lng, destination.lat])
        .setPopup(new Popup({ offset: 14 }).setText(`Drop: ${route?.destination?.text || 'Destination'}`))
        .addTo(map)

      map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 })
    })

    return () => {
      mapRef.current = null
      map.remove()
    }
  }, [hasPins, pickup?.lat, pickup?.lng, destination?.lat, destination?.lng, routeGeometry, route?.pickup?.text, route?.destination?.text])

  if (!hasPins) return null

  return (
    <div className="route-map-card">
      {mapError ? (
        <div className="route-map-fallback">
          <MapPin size={18} />
          <div>
            <strong>Route map preview unavailable</strong>
            <span>
              {pickup.lat.toFixed(4)}, {pickup.lng.toFixed(4)} to {destination.lat.toFixed(4)}, {destination.lng.toFixed(4)}
            </span>
          </div>
        </div>
      ) : (
        <div className="route-map-canvas" ref={containerRef} aria-label="Interactive route map" />
      )}
      <div className="route-map-bar">
        <div className="route-map-stats">
          <span className="legend-dot pickup" />
          <span>{route?.pickup?.text}</span>
          <span className="legend-sep">to</span>
          <span className="legend-dot destination" />
          <span>{route?.destination?.text}</span>
        </div>
        <div className="route-map-meta">
          {metrics && (
            <span className="tabular-figures">
              {metrics.distance_km} km · ~{metrics.duration_minutes} min
            </span>
          )}
          {onAdjustPins && (
            <button type="button" className="recenter-button" onClick={onAdjustPins}>
              <Pencil size={12} /> Adjust pins
            </button>
          )}
          {!mapError && (
            <button
              type="button"
              className="recenter-button"
              onClick={() => boundsRef.current && mapRef.current?.fitBounds(boundsRef.current, { padding: 48, maxZoom: 15 })}
            >
              <LocateFixed size={13} /> Center
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
