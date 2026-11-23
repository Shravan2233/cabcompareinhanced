// Location autocomplete, reverse geocoding, and optional Google Maps routing.
// Uses Google Maps Platform when VITE_GOOGLE_MAPS_API_KEY is set, and falls back
// automatically to free OpenStreetMap endpoints on the CabCompare backend.
const KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY
const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '')
const isLocalDefaultUrl = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(configuredApiBase)
export const API_BASE =
  import.meta.env.DEV && (!configuredApiBase || isLocalDefaultUrl)
    ? ''
    : (configuredApiBase || 'http://127.0.0.1:5000')
export const mapsEnabled = Boolean(KEY)

let loader
function loadMaps() {
  if (!mapsEnabled) return Promise.reject(new Error('Google Maps key is not configured'))
  if (window.google?.maps?.importLibrary) return Promise.resolve()
  if (!loader) {
    loader = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(KEY)}&loading=async&v=weekly`
      script.async = true
      script.onload = resolve
      script.onerror = () => { loader = null; reject(new Error('Google Maps failed to load')) }
      document.head.appendChild(script)
    })
  }
  return loader
}

export async function newSessionToken() {
  if (!mapsEnabled) return null
  await loadMaps()
  const { AutocompleteSessionToken } = await window.google.maps.importLibrary('places')
  return new AutocompleteSessionToken()
}

export async function suggestPlaces(input, sessionToken, near = null) {
  if (!mapsEnabled) {
    const params = new URLSearchParams({ q: input })
    if (near?.lat != null && near?.lng != null) {
      params.set('lat', String(near.lat))
      params.set('lng', String(near.lng))
    }
    const response = await fetch(`${API_BASE}/api/places/suggest?${params.toString()}`)
    if (!response.ok) return []
    const data = await response.json()
    return Array.isArray(data.suggestions) ? data.suggestions : []
  }

  await loadMaps()
  const { AutocompleteSuggestion } = await window.google.maps.importLibrary('places')
  const { suggestions } = await AutocompleteSuggestion.fetchAutocompleteSuggestions({
    input, sessionToken, includedRegionCodes: ['in'],
  })
  return suggestions
    .filter((item) => item.placePrediction)
    .map(({ placePrediction: p }) => ({
      id: p.placeId,
      main: p.mainText?.text || p.text.text,
      secondary: p.secondaryText?.text || '',
      text: p.text.text,
      prediction: p,
    }))
}

export async function placeCoordinates(suggestion) {
  if (suggestion.lat != null && suggestion.lng != null) {
    return { text: suggestion.text, lat: suggestion.lat, lng: suggestion.lng }
  }
  const place = suggestion.prediction.toPlace()
  await place.fetchFields({ fields: ['location'] })
  return { text: suggestion.text, lat: place.location.lat(), lng: place.location.lng() }
}

export async function reverseGeocode(lat, lng) {
  if (!mapsEnabled) {
    const params = new URLSearchParams({ lat: String(lat), lng: String(lng) })
    const response = await fetch(`${API_BASE}/api/places/reverse?${params.toString()}`)
    if (!response.ok) throw new Error('Could not resolve coordinates')
    const data = await response.json()
    if (!data?.text) throw new Error('No address found')
    return data.text
  }

  await loadMaps()
  const { Geocoder } = await window.google.maps.importLibrary('geocoding')
  const { results } = await new Geocoder().geocode({ location: { lat, lng } })
  if (!results?.length) throw new Error('No address found')
  return results[0].formatted_address
}

// Real driving distance and traffic-aware time (when Google Maps key is configured).
export async function routeMetrics(from, to) {
  await loadMaps()
  const { Route } = await window.google.maps.importLibrary('routes')
  const point = (p) => (p.lat != null && p.lng != null ? { lat: p.lat, lng: p.lng } : p.text)
  const { routes } = await Route.computeRoutes({
    origin: point(from), destination: point(to),
    travelMode: 'DRIVING', routingPreference: 'TRAFFIC_AWARE',
    fields: ['distanceMeters', 'durationMillis'],
  })
  const best = routes?.[0]
  if (!best?.distanceMeters) throw new Error('No route found')
  return {
    distance_km: Math.round(best.distanceMeters / 100) / 10,
    duration_minutes: Math.max(1, Math.round(best.durationMillis / 60000)),
  }
}
