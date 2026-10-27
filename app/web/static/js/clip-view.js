// Clip screen: the proxy video with the transparent overlay layer on top, range controls,
// the overlay panel and the export panel. Everything drawn comes from the server.

import { api, errorFromResponse } from './api.js';
import { el, errorNode } from './dom.js';
import { clock, dateTime } from './format.js';
import { createExportPanel } from './export-panel.js';
import { createOverlayPanel } from './overlay-panel.js';
import { clipIsBusy } from './status.js';

const POLL_MS = 1000; // clip refresh while the clip is still being prepared
const TICK_MS = 400; // overlay layer refresh while the video plays
const SAVE_MS = 150; // quiet time before a settings change is saved
const PREVIEW_WIDTH = 720; // px, the width the server renders the overlay layer at

const configBody = (config) => ({ mount: config.mount, overlays: config.overlays, range: config.range });

export function renderClip(root, clipId) {
  const s = {
    alive: true,
    clip: null,
    catalog: null,
    config: null,
    savedJson: null,
    pollTimer: null,
    saveTimer: null,
    saving: null,
    saveAgain: false,
    ticker: null,
    layerUrl: null,
    layerBusy: false,
    layerQueued: false,
    guides: false,
  };
  const id = encodeURIComponent(clipId);

  // Player and overlay layer. The layer sits on the video and is drawn by the server.
  const video = el('video', { class: 'media-video', controls: true, preload: 'auto' });
  const media = el('div', { class: 'media' }, video);
  const layer = el('img', { class: 'overlay-layer', alt: '', hidden: true });
  const stageMessage = el('div', { class: 'stage-message', hidden: true });
  const stage = el('div', { class: 'stage' }, media, layer, stageMessage);

  // Range, guides, status
  const rangeText = el('span', { class: 'range-text' });
  const inButton = el('button', { type: 'button', class: 'btn', text: 'Set in', onclick: () => setPoint('start') });
  const outButton = el('button', { type: 'button', class: 'btn', text: 'Set out', onclick: () => setPoint('end') });
  const clearButton = el('button', { type: 'button', class: 'btn ghost', text: 'Clear range', onclick: clearRange });
  const guides = el(
    'label',
    { class: 'check' },
    el('input', {
      type: 'checkbox',
      onchange: (event) => {
        s.guides = event.target.checked;
        refreshLayer({ force: true });
      },
    }),
    ' Safe-area guides (preview only)',
  );
  const status = el('span', { class: 'save-status', role: 'status', text: 'Loading' });
  const notice = el('div', { class: 'notice error', role: 'alert', hidden: true });
  const previewNote = el('p', { class: 'hint' });
  const title = el('h1', { class: 'clip-title' });
  const subtitle = el('p', { class: 'hint' });

  const overlays = createOverlayPanel({ onEdit: edit });
  const exporter = createExportPanel({ clipId, hasEnabledOverlay, beforeExport: flush });

  root.append(
    el(
      'header',
      { class: 'clip-head' },
      el('a', { class: 'back', href: '#/', text: 'Back to library' }),
      title,
      subtitle,
    ),
    el(
      'section',
      { class: 'clip-layout' },
      el(
        'div',
        { class: 'main' },
        stage,
        el('div', { class: 'toolbar' }, inButton, outButton, clearButton, rangeText, guides),
        el('div', { class: 'toolbar' }, status),
        notice,
        previewNote,
      ),
      el('aside', { class: 'side' }, overlays.element, exporter.element),
    ),
  );

  video.addEventListener('loadedmetadata', fitStage);
  video.addEventListener('play', startTicker);
  video.addEventListener('pause', () => {
    stopTicker();
    refreshLayer({ force: true });
  });
  video.addEventListener('ended', () => {
    stopTicker();
    refreshLayer({ force: true });
  });
  video.addEventListener('seeked', () => refreshLayer({ force: true }));
  video.addEventListener('error', () => {
    if (s.clip?.playable) {
      stageMessage.hidden = false;
      stageMessage.textContent = 'This browser cannot play the preview.';
    }
  });

  // Painting

  function paintAll() {
    if (!s.clip) return;
    paintHeader();
    paintStage();
    if (s.config && s.catalog) {
      paintRange();
      overlays.update(s.catalog, s.config);
    }
  }

  function paintHeader() {
    title.textContent = s.clip.name;
    subtitle.textContent = [s.clip.camera, dateTime(s.clip.recorded_at), clock(s.clip.duration_s)]
      .filter(Boolean)
      .join(' · ');
  }

  function paintStage() {
    const clip = s.clip;
    const ratio = clip.display_width && clip.display_height ? clip.display_width / clip.display_height : 16 / 9;
    stage.style.setProperty('--ar', String(ratio));
    stage.style.setProperty('--ar-inv', String(1 / ratio));
    const playable = clip.playable;
    if (playable && video.getAttribute('src') !== clip.proxy_url) video.src = clip.proxy_url;
    video.hidden = !playable;
    layer.hidden = !playable || !s.layerUrl;
    stageMessage.hidden = playable;
    stageMessage.textContent = playable ? '' : describeStage(clip);
    inButton.disabled = !playable;
    outButton.disabled = !playable;
  }

  function paintRange() {
    const range = s.config.range ?? {};
    const duration = s.clip.duration_s;
    const whole = range.start === null && range.end === null;
    if (whole) {
      rangeText.textContent = `Whole clip, ${clock(duration)}`;
      return;
    }
    const start = range.start ?? 0;
    const end = range.end ?? duration;
    rangeText.textContent = `${clock(start)}–${clock(end)} (${clock(end - start)})`;
  }

  /** Sideways proxies: the browser shows the stored landscape frame of a portrait clip. Turn it upright. */
  function fitStage() {
    if (!s.clip) return;
    const sideways = s.clip.orientation === 'portrait' && video.videoWidth > video.videoHeight;
    media.classList.toggle('turned', sideways);
  }

  // Edits and autosave

  function edit(mutate) {
    if (!s.config) return;
    mutate(s.config);
    paintAll();
    scheduleSave();
  }

  function setPoint(which) {
    if (!s.clip?.playable) return;
    const at = Math.round(video.currentTime * 100) / 100;
    edit((cfg) => { cfg.range = { ...cfg.range, [which]: at }; });
  }

  function clearRange() {
    edit((cfg) => { cfg.range = { start: null, end: null }; });
  }

  function hasEnabledOverlay() {
    return Object.values(s.config?.overlays ?? {}).some((entry) => entry.enabled);
  }

  function setStatus(text, kind = '') {
    status.textContent = text;
    status.className = `save-status ${kind}`.trim();
  }

  function say(content) {
    notice.hidden = !content;
    notice.replaceChildren(content ?? '');
  }

  function scheduleSave() {
    clearTimeout(s.saveTimer);
    s.saveTimer = setTimeout(save, SAVE_MS);
    setStatus('Unsaved changes');
  }

  /** Saves never overlap: a change made during a save is sent once that save finishes. */
  function save() {
    clearTimeout(s.saveTimer);
    s.saveTimer = null;
    if (s.saving) {
      s.saveAgain = true;
      return s.saving;
    }
    s.saving = saveNow().finally(() => {
      s.saving = null;
      if (s.saveAgain) {
        s.saveAgain = false;
        save();
      }
    });
    return s.saving;
  }

  async function saveNow() {
    const body = configBody(s.config);
    const json = JSON.stringify(body);
    if (json === s.savedJson) {
      setStatus('Saved', 'ok');
      return;
    }
    setStatus('Saving…');
    try {
      await api(`/api/clips/${id}/config`, { method: 'PUT', body });
      s.savedJson = json;
      setStatus('Saved', 'ok');
      say(null);
      refreshLayer({ force: true });
    } catch (error) {
      setStatus('Not saved', 'error');
      say(errorNode(error));
    }
  }

  /** Save any pending change now and wait until nothing is in flight. */
  async function flush() {
    if (s.saveTimer) save();
    while (s.saving) await s.saving;
  }

  // Overlay layer

  /**
   * Fetch the overlay layer for the current position. Forced requests (pause, seek, setting change)
   * are queued behind a request in flight. Ticks while playing are skipped instead.
   */
  async function refreshLayer({ force = false } = {}) {
    if (!s.alive || !s.clip?.playable) return;
    if (s.layerBusy) {
      if (force) s.layerQueued = true;
      return;
    }
    s.layerBusy = true;
    try {
      const params = new URLSearchParams({ t: video.currentTime.toFixed(3), w: String(PREVIEW_WIDTH) });
      if (s.guides) params.set('guides', 'true');
      const response = await fetch(`/api/clips/${id}/overlay.png?${params}`, { cache: 'no-store' });
      if (!s.alive) return;
      if (!response.ok) {
        previewNote.textContent = (await errorFromResponse(response)).message;
        return;
      }
      const blob = await response.blob();
      if (!s.alive) return;
      const previous = s.layerUrl;
      s.layerUrl = URL.createObjectURL(blob);
      layer.src = s.layerUrl;
      layer.hidden = false;
      if (previous) URL.revokeObjectURL(previous);
      previewNote.textContent = '';
    } catch (error) {
      if (s.alive) previewNote.textContent = error.message;
    } finally {
      s.layerBusy = false;
      if (s.alive && s.layerQueued) {
        s.layerQueued = false;
        refreshLayer({ force: true });
      }
    }
  }

  function startTicker() {
    if (!s.ticker) s.ticker = setInterval(() => refreshLayer(), TICK_MS);
    refreshLayer();
  }

  function stopTicker() {
    clearInterval(s.ticker);
    s.ticker = null;
  }

  // Loading and polling while the clip is still being prepared

  async function load() {
    try {
      const first = !s.config;
      const [clip, catalog, config] = await Promise.all([
        api(`/api/clips/${id}`),
        api(`/api/overlays?clip=${id}`),
        first ? api(`/api/clips/${id}/config`) : null,
      ]);
      if (!s.alive) return;
      s.clip = clip;
      s.catalog = catalog;
      if (config) {
        s.config = config;
        s.savedJson = JSON.stringify(configBody(config));
        setStatus('Saved', 'ok');
      }
      paintAll();
      if (clip.playable && !s.layerUrl) refreshLayer({ force: true });
      schedulePoll();
    } catch (error) {
      if (s.alive) {
        setStatus('');
        say(errorNode(error));
      }
    }
  }

  function schedulePoll() {
    clearTimeout(s.pollTimer);
    s.pollTimer = s.alive && clipIsBusy(s.clip) ? setTimeout(load, POLL_MS) : null;
  }

  load();

  return {
    dispose() {
      if (s.saveTimer) save(); // keep a change made just before leaving the page
      s.alive = false;
      clearTimeout(s.pollTimer);
      stopTicker();
      exporter.dispose();
      if (s.layerUrl) URL.revokeObjectURL(s.layerUrl);
      video.pause();
      video.removeAttribute('src');
      video.load();
    },
  };
}

function describeStage(clip) {
  if (clip.missing) return 'The source file is missing, so the preview and export are disabled.';
  if (clip.proxy_status === 'failed') return `The preview could not be made: ${clip.error ?? 'unknown error'}`;
  if (clip.proxy_status === 'running') return `Preparing the preview… ${Math.round(clip.proxy_progress ?? 0)}%`;
  return 'Preparing the preview…';
}
