import { useEffect, useRef, useState } from 'react'
import { MapPin, X } from 'lucide-react'
import { mapsEnabled, newSessionToken, placeCoordinates, suggestPlaces } from './maps.js'

// Combobox with place autocomplete (OpenStreetMap by default, Google Places if configured).
export default function LocationInput({
  kicker, label, dotClass, value, near = null, onTyping, onPick, placeholder, inputRef, children,
}) {
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [busy, setBusy] = useState(false)
  const [searched, setSearched] = useState(false)
  const [searchError, setSearchError] = useState('')
  const token = useRef(null)
  const wrapper = useRef(null)
  const text = value.text || ''
  const nearLat = near?.lat ?? null
  const nearLng = near?.lng ?? null

  useEffect(() => {
    if (!open || text.trim().length < 2 || value.lat != null) {
      setItems([])
      setBusy(false)
      setSearched(false)
      setSearchError('')
      return undefined
    }
    let cancelled = false
    setBusy(true)
    setSearchError('')
    const timer = setTimeout(async () => {
      try {
        if (mapsEnabled) token.current = token.current || (await newSessionToken())
        const bias = nearLat != null && nearLng != null ? { lat: nearLat, lng: nearLng } : null
        const found = await suggestPlaces(text.trim(), token.current, bias)
        if (!cancelled) {
          setItems(found.slice(0, 6))
          setActive(-1)
          setSearched(true)
          setSearchError('')
        }
      } catch (err) {
        if (!cancelled) {
          setItems([])
          setSearched(true)
          setSearchError(err?.message || 'Unable to reach location search.')
        }
      } finally {
        if (!cancelled) setBusy(false)
      }
    }, 220)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [text, open, value.lat, nearLat, nearLng])

  useEffect(() => {
    const close = (event) => { if (!wrapper.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  async function choose(item) {
    setOpen(false)
    setItems([])
    onPick({ text: item.text, lat: item.lat, lng: item.lng })
    try {
      onPick(await placeCoordinates(item))
    } catch {
      /* label alone is still usable */
    }
    token.current = null
  }

  function onKeyDown(event) {
    if (!open || !items.length) return
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((i) => (i + 1) % items.length) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((i) => (i <= 0 ? items.length - 1 : i - 1)) }
    else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(items[active]) }
    else if (event.key === 'Escape') setOpen(false)
  }

  const listId = `${kicker}-suggestions`
  return (
    <div className="location-input" ref={wrapper}>
      <span className={`location-dot ${dotClass}`} />
      <span className="input-copy">
        <span>{kicker}</span>
        <input
          ref={inputRef} aria-label={label} value={text} placeholder={placeholder} maxLength={160}
          role="combobox" aria-expanded={open && items.length > 0} aria-controls={listId} aria-autocomplete="list"
          autoComplete="off" onKeyDown={onKeyDown} onFocus={() => setOpen(true)}
          onChange={(event) => { onTyping(event.target.value); setOpen(true) }}
        />
      </span>
      {text && (
        <button
          type="button" className="clear-button" aria-label={`Clear ${label.toLowerCase()}`}
          onClick={() => { onTyping(''); setItems([]); inputRef?.current?.focus() }}
        >
          <X size={14} />
        </button>
      )}
      {children}
      {open && (items.length > 0 || busy || searched || searchError) && (
        <ul className="suggestions" id={listId} role="listbox">
          {items.map((item, index) => (
            <li
              key={item.id} role="option" aria-selected={index === active} className={index === active ? 'active' : ''}
              onMouseDown={(event) => { event.preventDefault(); choose(item) }} onMouseEnter={() => setActive(index)}
            >
              <MapPin size={16} />
              <span>
                <strong>{item.main}</strong>
                <small>{item.secondary}</small>
              </span>
            </li>
          ))}
          {busy && !items.length && <li className="suggestions-note">Searching places…</li>}
          {!busy && searchError && <li className="suggestions-note suggestions-error">{searchError}</li>}
          {!busy && !searchError && searched && !items.length && (
            <li className="suggestions-note">No suggestions yet — keep typing or enter full area/city</li>
          )}
          {items.length > 0 && (
            <li className="suggestions-note powered">
              {mapsEnabled ? 'Powered by Google' : 'Suggestions via OpenStreetMap'}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
