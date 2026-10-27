// Export panel: start an export with the saved settings and range, and the live job list.

import { api } from './api.js';
import { el, errorNode } from './dom.js';
import { clock } from './format.js';
import { jobIsActive } from './status.js';

const POLL_MS = 1000;
const SHOWN_JOBS = 20;
const PRESETS = [
  ['original', 'Original (source size)'],
  ['social', 'Social (1080 px short side)'],
];

/**
 * Returns { element, dispose }. `hasEnabledOverlay()` tells whether any overlay is switched on;
 * `beforeExport()` must save the latest settings so the export uses them.
 */
export function createExportPanel({ clipId, hasEnabledOverlay, beforeExport }) {
  const s = { alive: true, jobs: [], timer: null };

  const preset = el(
    'select',
    { class: 'control', 'aria-label': 'Resolution preset' },
    PRESETS.map(([value, text]) => el('option', { value, text })),
  );
  const exportButton = el('button', { type: 'button', class: 'btn primary', text: 'Export', onclick: startExport });
  const notice = el('div', { class: 'notice', role: 'alert', hidden: true });
  const empty = el('p', { class: 'hint', text: 'No exports yet.' });
  const list = el('ul', { class: 'jobs' });
  const element = el(
    'section',
    { class: 'panel export-panel' },
    el('h2', { text: 'Export' }),
    el('div', { class: 'row' }, preset, exportButton),
    notice,
    el('h3', { text: 'Jobs' }),
    empty,
    list,
  );

  function say(content) {
    notice.hidden = !content;
    notice.replaceChildren(content ?? '');
  }

  async function startExport() {
    if (!hasEnabledOverlay() && !window.confirm('No overlay is enabled. Export the plain clip without overlays?')) {
      return;
    }
    exportButton.disabled = true;
    say(null);
    try {
      await beforeExport();
      await api(`/api/clips/${encodeURIComponent(clipId)}/export`, { method: 'POST', body: { preset: preset.value } });
    } catch (error) {
      say(errorNode(error));
    } finally {
      exportButton.disabled = false;
    }
    await loadJobs();
  }

  async function loadJobs() {
    try {
      const jobs = await api('/api/jobs');
      if (!s.alive) return;
      s.jobs = jobs;
      paint();
    } catch (error) {
      if (s.alive) say(errorNode(error));
    } finally {
      schedule();
    }
  }

  function schedule() {
    clearTimeout(s.timer);
    s.timer = s.alive && s.jobs.some(jobIsActive) ? setTimeout(loadJobs, POLL_MS) : null;
  }

  function paint() {
    const shown = s.jobs.slice(-SHOWN_JOBS).reverse();
    empty.hidden = s.jobs.length > 0;
    list.replaceChildren(...shown.map(jobRow));
  }

  async function cancelJob(job) {
    try {
      await api(`/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' });
    } catch (error) {
      say(errorNode(error));
    }
    await loadJobs();
  }

  function jobRow(job) {
    const whole = job.start === null && job.end === null;
    const range = whole ? 'whole clip' : `${clock(job.start ?? 0)}–${job.end === null ? 'end' : clock(job.end)}`;
    const active = jobIsActive(job);
    const percent = Math.round(job.progress ?? 0);
    let progress = null;
    if (active) {
      const timing = job.state === 'running'
        ? job.eta_s === null || job.eta_s === undefined ? 'estimating time left' : `${clock(job.eta_s)} left`
        : 'waiting for the export queue';
      progress = el(
        'div',
        { class: 'job-progress' },
        el('progress', { max: 100, value: job.progress ?? 0 }),
        el('span', { text: `${percent}% · ${timing}` }),
      );
    }
    const finished = job.state === 'completed' && job.output_url;
    const links = finished
      ? [
          el('a', { href: job.output_url, target: '_blank', rel: 'noopener', text: 'Play' }),
          el('a', { href: `${job.output_url}?download=1`, download: job.output_name ?? 'export.mp4', text: 'Download' }),
        ]
      : [];
    return el(
      'li',
      { class: `job job-${job.state}` },
      el('div', { class: 'job-head' }, el('strong', { text: job.clip_name }), el('span', { class: 'badge', text: job.state })),
      el('p', { class: 'hint', text: `${job.preset} · ${range}` }),
      progress,
      job.state === 'failed' || job.state === 'cancelled' ? el('p', { class: 'hint', text: job.reason ?? '' }) : null,
      el(
        'div',
        { class: 'job-actions' },
        ...links,
        active ? el('button', { type: 'button', class: 'btn small danger', text: 'Cancel', onclick: () => cancelJob(job) }) : null,
      ),
    );
  }

  loadJobs();

  return {
    element,
    dispose() {
      s.alive = false;
      clearTimeout(s.timer);
    },
  };
}
