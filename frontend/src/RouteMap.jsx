import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { LocateFixed, Pencil } from 'lucide-react'
import { addFreeTileLayer, createPinIcon } from './leafletTiles.js'

export default function RouteMap({ route, routeCoords, routeGeometry, metrics, onAdjustPins = null }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const boundsRef = useRef(null)

  const pickup = routeCoords?.pickup
  const destination = routeCoords?.destination
  const hasPins = pickup?.lat != null && pickup?.lng != null && destination?.lat != null && destination?.lng != null

  useEffect(() => {
    if (!hasPins || !containerRef.current) return undefined

    const latLngLine = Array.isArray(routeGeometry) && routeGeometry.length >= 2
      ? routeGeometry.map(([lng, lat]) => [lat, lng])
      : [[pickup.lat, pickup.lng], [destination.lat, destination.lng]]

    const bounds = L.latLngBounds([...latLngLine, [pickup.lat, pickup.lng], [destination.lat, destination.lng]])
    boundsRef.current = bounds

    const map = L.map(containerRef.current, {
      zoomControl: true,
      attributionControl: true,
    })
    mapRef.current = map
    addFreeTileLayer(map)

    // Subtle white casing underneath the green route line for crisp street contrast.
    L.polyline(latLngLine, { color: '#ffffff', weight: 7, opacity: 0.9, lineCap: 'round', lineJoin: 'round' }).addTo(map)
    L.polyline(latLngLine, { color: '#087e68', weight: 4, opacity: 0.95, lineCap: 'round', lineJoin: 'round' }).addTo(map)

    L.marker([pickup.lat, pickup.lng], { icon: createPinIcon('pickup') })
      .bindPopup(`Pickup: ${route?.pickup?.text || 'Start'}`)
      .addTo(map)

    L.marker([destination.lat, destination.lng], { icon: createPinIcon('destination') })
      .bindPopup(`Drop: ${route?.destination?.text || 'Destination'}`)
      .addTo(map)

    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 })
    const resizeTimer = setTimeout(() => {
      map.invalidateSize()
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 })
    }, 80)

    return () => {
      clearTimeout(resizeTimer)
      mapRef.current = null
      map.remove()
    }
  }, [hasPins, pickup?.lat, pickup?.lng, destination?.lat, destination?.lng, routeGeometry, route?.pickup?.text, route?.destination?.text])

  if (!hasPins) return null

  return (
    <div className="route-map-card">
      <div className="route-map-canvas" ref={containerRef} aria-label="Interactive route map" />
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
          <button
            type="button"
            className="recenter-button"
            onClick={() => boundsRef.current && mapRef.current?.fitBounds(boundsRef.current, { padding: [40, 40], maxZoom: 15 })}
          >
            <LocateFixed size={13} /> Center
          </button>
        </div>
      </div>
    </div>
  )
}
