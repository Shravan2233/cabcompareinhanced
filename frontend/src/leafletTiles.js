import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const OSM_STANDARD = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const OSM_HOT = 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png'

/** Attach free, open-source OpenStreetMap raster tiles (zero API keys) with OSM HOT fallback. */
export function addFreeTileLayer(map) {
  let switchedToFallback = false
  let errorCount = 0

  const layer = L.tileLayer(OSM_STANDARD, {
    maxZoom: 19,
    crossOrigin: 'anonymous',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  })

  layer.on('tileerror', () => {
    errorCount += 1
    if (!switchedToFallback && errorCount >= 3) {
      switchedToFallback = true
      layer.setUrl(OSM_HOT)
    }
  })

  layer.addTo(map)
  return layer
}

/** Build a crisp SVG teardrop map pin icon for Leaflet markers. */
export function createPinIcon(kind, { draggable = false } = {}) {
  const fill = kind === 'pickup' ? '#087e68' : '#ed7659'
  const svg = `
    <svg class="map-teardrop-svg${draggable ? ' draggable' : ''}" width="32" height="40" viewBox="0 0 32 40" fill="none" aria-hidden="true">
      <path d="M16 2C8.82 2 3 7.82 3 15c0 9.6 13 22 13 22s13-12.4 13-22C29 7.82 23.18 2 16 2Z" fill="${fill}" stroke="#ffffff" stroke-width="2.5"/>
      <circle cx="16" cy="14.5" r="5" fill="#ffffff"/>
    </svg>
  `.trim()
  return L.divIcon({
    className: 'cabcompare-div-icon',
    html: svg,
    iconSize: [32, 40],
    iconAnchor: [16, 37],
    popupAnchor: [0, -34],
  })
}
