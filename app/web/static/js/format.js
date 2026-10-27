// Display formatting for times, sizes and labels.

/** Seconds as m:ss, or h:mm:ss from one hour. Missing values show an en dash. */
export function clock(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '–';
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mmss = `${hours ? String(minutes).padStart(2, '0') : minutes}:${String(secs).padStart(2, '0')}`;
  return hours ? `${hours}:${mmss}` : mmss;
}

export function bytes(count) {
  if (!Number.isFinite(count)) return '';
  if (count >= 1e9) return `${(count / 1e9).toFixed(1)} GB`;
  if (count >= 1e6) return `${Math.round(count / 1e6)} MB`;
  return `${count} B`;
}

/** An ISO 8601 timestamp in the viewer's local time zone. */
export function dateTime(iso) {
  if (!iso) return 'time unknown';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** "top-left" becomes "Top left", "bike" becomes "Bike". */
export function label(text) {
  const spaced = String(text).replace(/[-_]/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
