// Library screen: uploads by drag-and-drop or picker, folder import by reference, and the clip cards.

import { ApiError, api, uploadFile } from './api.js';
import { el, errorNode } from './dom.js';
import { bytes, clock, dateTime } from './format.js';
import { clipIsBusy, previewText, telemetryText } from './status.js';

const MEDIA_RE = /\.(mp4|mov)$/i;
const PROXY_RE = /\.lrf$/i;
const POLL_MS = 1000;

// The upload queue belongs to the page, not to the view, so a file that is still copying
// keeps going when the user opens a clip. Only the library on screen gets the repaints.
const uploads = []; // { name, status: waiting | uploading | done | error, progress, message, error }
let queue = Promise.resolve();
let activeView = null; // { repaint, reload } of the library on screen

export function renderLibrary(root) {
  const s = { alive: true, clips: [], loading: false, reloadQueued: false, timer: null };

  const notice = el('div', { class: 'notice', role: 'status', hidden: true });
  const uploadList = el('ul', { class: 'uploads', hidden: true });
  const fileInput = el('input', {
    type: 'file',
    multiple: true,
    accept: '.mp4,.mov,.lrf',
    hidden: true,
    onchange: (event) => {
      queueUploads([...event.target.files]);
      event.target.value = ''; // allow picking the same file again
    },
  });
  const dropZone = el(
    'div',
    {
      class: 'drop-zone',
      role: 'button',
      tabindex: 0,
      'aria-label': 'Drop video files here, or press Enter to choose files',
      onclick: () => fileInput.click(),
      onkeydown: (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          fileInput.click();
        }
      },
      ondragover: (event) => {
        event.preventDefault();
        dropZone.classList.add('over');
      },
      ondragleave: () => dropZone.classList.remove('over'),
      ondrop: (event) => {
        event.preventDefault();
        dropZone.classList.remove('over');
        queueUploads([...event.dataTransfer.files]);
      },
    },
    el('strong', { text: 'Drop MP4, MOV or LRF files here' }),
    el('span', { class: 'hint', text: 'or click to choose files. They are copied into the workspace.' }),
  );
  const folderInput = el('input', { type: 'text', class: 'grow', 'aria-label': 'Folder to import' });
  const importButton = el('button', { type: 'button', class: 'btn', text: 'Add from folder', onclick: importFolder });
  const empty = el('p', { class: 'hint', text: 'No clips yet. Drop files above, or add a folder.' });
  const grid = el('div', { class: 'clip-grid' });

  root.append(
    el(
      'section',
      { class: 'library' },
      el('h1', { text: 'Library' }),
      el('div', { class: 'panel' }, dropZone, fileInput, uploadList),
      el(
        'div',
        { class: 'panel' },
        el('h2', { text: 'Add from folder' }),
        el('p', { class: 'hint', text: 'Clips in this folder are referenced where they are. Nothing is copied.' }),
        el('div', { class: 'row' }, folderInput, importButton),
      ),
      notice,
      empty,
      grid,
    ),
  );

  function say(content, kind = 'info') {
    notice.className = `notice ${kind}`;
    notice.hidden = !content;
    notice.replaceChildren(content ?? '');
  }

  // Uploads

  function queueUploads(files) {
    const media = files.filter((file) => MEDIA_RE.test(file.name));
    const proxies = files.filter((file) => PROXY_RE.test(file.name));
    for (const file of files) {
      if (!media.includes(file) && !proxies.includes(file)) {
        uploads.push({
          name: file.name,
          status: 'error',
          progress: 0,
          error: new ApiError(`${file.name}: not a video file (MP4, MOV or LRF)`),
        });
      }
    }
    // MP4s go first, so that each LRF can pair with the clip it belongs to.
    for (const file of [...media, ...proxies]) {
      const row = { name: file.name, status: 'waiting', progress: 0 };
      uploads.push(row);
      queue = queue.then(() => runUpload(file, row));
    }
    activeView?.repaint();
  }

  async function runUpload(file, row) {
    row.status = 'uploading';
    activeView?.repaint();
    try {
      const result = await uploadFile(file, (fraction) => {
        row.progress = fraction;
        activeView?.repaint();
      });
      row.status = 'done';
      row.message = result.message;
    } catch (error) {
      row.status = 'error';
      row.error = error;
    }
    activeView?.repaint();
    activeView?.reload();
  }

  function paintUploads() {
    uploadList.hidden = uploads.length === 0;
    uploadList.replaceChildren(...uploads.map(uploadRow));
  }

  function uploadRow(row) {
    let state;
    if (row.status === 'uploading') {
      state = row.progress >= 1 ? 'checking the file' : `uploading ${Math.round(row.progress * 100)}%`;
    } else if (row.status === 'done') {
      state = row.message;
    } else {
      state = row.status === 'error' ? 'failed' : 'waiting';
    }
    return el(
      'li',
      { class: `upload ${row.status}` },
      el('div', { class: 'upload-head' }, el('span', { text: row.name }), el('span', { class: 'hint', text: state })),
      row.status === 'uploading' ? el('progress', { max: 1, value: row.progress }) : null,
      row.status === 'error' ? errorNode(row.error) : null,
    );
  }

  // Folder import

  async function importFolder() {
    importButton.disabled = true;
    say('Reading the folder. Probing each video takes a moment.');
    try {
      const result = await api('/api/import-folder', {
        method: 'POST',
        body: { path: folderInput.value.trim() || null },
      });
      const summary = el(
        'div',
        {},
        el('p', { text: `${result.folder}: ${result.added.length} added, ${result.existing.length} already in the library.` }),
        result.errors.length
          ? el('ul', {}, result.errors.map((item) => el('li', { text: `${item.file}: ${item.error}` })))
          : null,
      );
      say(summary, result.errors.length ? 'warn' : 'ok');
      await loadClips();
    } catch (error) {
      say(errorNode(error), 'error');
    } finally {
      importButton.disabled = false;
    }
  }

  // Clip list, polled while any clip is still being prepared

  async function loadClips() {
    if (s.loading) {
      s.reloadQueued = true; // the response in flight may predate the change, so ask again
      return;
    }
    s.loading = true;
    try {
      const clips = await api('/api/clips');
      if (!s.alive) return;
      s.clips = clips;
      paintClips();
    } catch (error) {
      if (s.alive) say(errorNode(error), 'error');
    } finally {
      s.loading = false;
      if (s.alive && s.reloadQueued) {
        s.reloadQueued = false;
        loadClips();
      } else {
        schedule();
      }
    }
  }

  function schedule() {
    clearTimeout(s.timer);
    s.timer = s.alive && s.clips.some(clipIsBusy) ? setTimeout(loadClips, POLL_MS) : null;
  }

  function paintClips() {
    empty.hidden = s.clips.length > 0;
    grid.replaceChildren(...s.clips.map(clipCard));
  }

  function clipCard(clip) {
    const thumb = clip.thumbnail_url
      ? el('img', { class: 'thumb', src: clip.thumbnail_url, alt: '', loading: 'lazy' })
      : el('div', { class: 'thumb placeholder', text: clip.thumbnail_status === 'failed' ? 'no thumbnail' : 'thumbnail…' });
    const status = [telemetryText(clip), previewText(clip)].filter(Boolean).join(' · ');
    return el(
      'article',
      { class: `card${clip.missing ? ' missing' : ''}` },
      el(
        'a',
        { class: 'card-link', href: `#/clip/${encodeURIComponent(clip.id)}` },
        thumb,
        el(
          'div',
          { class: 'card-body' },
          el('h3', { text: clip.name }),
          el('p', { class: 'meta', text: `${clock(clip.duration_s)} · ${dateTime(clip.recorded_at)}` }),
          el('p', { class: 'meta', text: `${clip.camera ?? 'camera unknown'} · ${bytes(clip.size)}` }),
          el('p', { class: 'status-line', text: status }),
          clip.error ? el('p', { class: 'error-text', text: clip.error }) : null,
          clip.missing ? el('span', { class: 'badge bad', text: 'missing' }) : null,
        ),
      ),
      el(
        'div',
        { class: 'card-actions' },
        el('button', { type: 'button', class: 'btn small danger', text: 'Remove', onclick: () => removeClip(clip) }),
      ),
    );
  }

  async function removeClip(clip) {
    const question = clip.origin === 'upload'
      ? `Remove ${clip.name} from the library and delete its uploaded copy? This cannot be undone.`
      : `Remove ${clip.name} from the library? The original file is kept.`;
    if (!window.confirm(question)) return;
    try {
      await api(`/api/clips/${encodeURIComponent(clip.id)}`, { method: 'DELETE' });
      say(`${clip.name} removed.`, 'ok');
      await loadClips();
    } catch (error) {
      say(errorNode(error), 'error');
    }
  }

  // Start

  const view = { repaint: paintUploads, reload: loadClips };
  activeView = view;
  paintUploads();
  api('/api/workspace')
    .then((info) => {
      if (s.alive && !folderInput.value) folderInput.value = info.default_import_folder;
    })
    .catch((error) => {
      if (s.alive) say(errorNode(error), 'error');
    });
  loadClips();

  return {
    dispose() {
      s.alive = false;
      clearTimeout(s.timer);
      if (activeView === view) activeView = null;
    },
  };
}
