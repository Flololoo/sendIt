// Entry point. Hash routing: #/ is the library, #/clip/<id> is one clip.

import { renderClip } from './js/clip-view.js';
import { renderLibrary } from './js/library.js';

const main = document.getElementById('view');
let current = null;

function clipIdFromHash() {
  const match = /^#\/clip\/([^/?#]+)/.exec(location.hash);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function route() {
  current?.dispose();
  current = null;
  main.replaceChildren();
  const clipId = clipIdFromHash();
  current = clipId ? renderClip(main, clipId) : renderLibrary(main);
}

window.addEventListener('hashchange', route);
route();
