// Reading the background status fields that the server sends with clips and export jobs.

const ACTIVE_STATES = new Set(['pending', 'running']);

/** True while any background step of the clip (telemetry, thumbnail, proxy) is still going. */
export function clipIsBusy(clip) {
  return [clip.telemetry_status, clip.thumbnail_status, clip.proxy_status].some((state) => ACTIVE_STATES.has(state));
}

export function jobIsActive(job) {
  return job.state === 'queued' || job.state === 'running';
}

export function telemetryText(clip) {
  switch (clip.telemetry_status) {
    case 'pending':
    case 'running':
      return 'telemetry: reading';
    case 'done':
      return clip.telemetry_available ? 'telemetry available' : 'no telemetry';
    case 'failed':
      return 'telemetry failed';
    default:
      return '';
  }
}

export function previewText(clip) {
  switch (clip.proxy_status) {
    case 'lrf':
      return 'preview: camera proxy';
    case 'done':
      return 'preview ready';
    case 'pending':
      return 'preview queued';
    case 'running':
      return `preview ${Math.round(clip.proxy_progress ?? 0)}%`;
    case 'failed':
      return 'preview failed';
    default:
      return '';
  }
}
