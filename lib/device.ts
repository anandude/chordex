/**
 * device.ts
 * ---------
 * Chordex has no accounts. The browser mints a random id once and keeps it in
 * localStorage; the backend scopes saved songs to it, so the history is only
 * ever visible on this browser. Nothing about it identifies a person.
 *
 * Clearing site data, or using another browser or device, starts a new empty
 * history — that is the trade-off for not having a login.
 */

const STORAGE_KEY = "chordex.device";

//: Mirrors backend/library.py:valid_device_id.
const VALID = /^[A-Za-z0-9_-]{8,64}$/;

function generate(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    /* not available (older browser, insecure context) */
  }
  // Fallback: 16 random bytes as hex. Still unguessable, just less pretty.
  return Array.from({ length: 16 }, () =>
    Math.floor(Math.random() * 256)
      .toString(16)
      .padStart(2, "0")
  ).join("");
}

/**
 * This browser's device id, creating and persisting one on first use.
 * Returns "" during server rendering (and when storage is blocked), which the
 * API treats as "no history".
 */
export function getDeviceId(): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && VALID.test(existing)) return existing;
    const id = generate();
    window.localStorage.setItem(STORAGE_KEY, id);
    return id;
  } catch {
    // Private mode / storage disabled: the app still works, just without history.
    return "";
  }
}
