// Overlay controls, generated entirely from GET /api/overlays?clip=. No overlay id appears in this file:
// a newly registered overlay gets its toggle, settings and presets from its declared settings.

import { el } from './dom.js';
import { label } from './format.js';

/**
 * Returns { element, update(catalog, config) }. Every user change is passed to onEdit as a function
 * that mutates the clip's configuration; the clip screen then saves it.
 */
export function createOverlayPanel({ onEdit }) {
  const element = el('section', { class: 'panel overlay-panel' });
  let signature = null; // the catalog the controls were built from
  let mountControl = null;
  let rows = [];

  function update(catalog, config) {
    const next = JSON.stringify(catalog);
    if (next !== signature) {
      signature = next;
      build(catalog);
    }
    sync(catalog, config);
  }

  // Build once per catalog. Values are set afterwards by sync(), so a slider being dragged is not rebuilt.
  function build(catalog) {
    mountControl = segmented(
      catalog.mounts.map((mount) => [mount, label(mount)]),
      (mount) => onEdit((cfg) => { cfg.mount = mount; }),
    );
    rows = catalog.overlays.map((overlay) => overlayRow(overlay, catalog));
    element.replaceChildren(
      el('h2', { text: 'Overlays' }),
      field('Camera mount', mountControl.element),
      ...rows.map((row) => row.card),
    );
  }

  function sync(catalog, config) {
    mountControl.set(config.mount);
    catalog.overlays.forEach((overlay, index) => {
      const row = rows[index];
      const entry = config.overlays[overlay.id] ?? {};
      const on = overlay.available && Boolean(entry.enabled);
      row.toggle.checked = on;
      row.toggle.disabled = !overlay.available;
      row.reason.hidden = overlay.available;
      row.reason.textContent = overlay.reason ?? '';
      row.body.hidden = !on;
      row.position.value = entry.position ?? overlay.default_position;
      row.size.set(entry.size ?? overlay.default_size);
      for (const setting of row.settings) setting.sync(entry.settings?.[setting.key]);
    });
  }

  function overlayRow(overlay, catalog) {
    const id = overlay.id;
    const toggle = el('input', {
      type: 'checkbox',
      class: 'switch',
      'aria-label': `Enable ${overlay.name}`,
      onchange: (event) => onEdit((cfg) => { entryOf(cfg, id).enabled = event.target.checked; }),
    });
    const position = el(
      'select',
      {
        class: 'control',
        'aria-label': `${overlay.name} position`,
        onchange: (event) => onEdit((cfg) => { entryOf(cfg, id).position = event.target.value; }),
      },
      catalog.positions.map((name) => el('option', { value: name, text: label(name) })),
    );
    const size = segmented(
      catalog.sizes.map((code) => [code, code]),
      (code) => onEdit((cfg) => { entryOf(cfg, id).size = code; }),
    );
    const settings = overlay.settings.map((setting) => settingRow(id, setting));
    const reason = el('p', { class: 'reason', hidden: true });
    const body = el(
      'div',
      { class: 'overlay-body' },
      field('Position', position),
      field('Size', size.element),
      ...settings.map((setting) => setting.element),
    );
    const card = el(
      'article',
      { class: 'overlay-card' },
      el(
        'div',
        { class: 'overlay-head' },
        el('div', {}, el('strong', { text: overlay.name }), el('p', { class: 'hint', text: overlay.description })),
        toggle,
      ),
      reason,
      body,
    );
    return { toggle, reason, body, position, size, settings, card };
  }

  function settingRow(id, setting) {
    const write = (value) => onEdit((cfg) => { entryOf(cfg, id).settings[setting.key] = value; });
    const text = setting.label ?? setting.key;
    let control;
    let sync;
    let wrap;

    if (setting.type === 'bool') {
      control = el('input', {
        type: 'checkbox',
        class: 'switch',
        'aria-label': text,
        onchange: (event) => write(event.target.checked),
      });
      wrap = control;
      sync = (value) => { control.checked = Boolean(value ?? setting.default); };
    } else if (setting.type === 'enum') {
      const choices = setting.choices ?? [];
      const byText = new Map(choices.map((choice) => [String(choice), choice]));
      if (choices.length <= 3) {
        const seg = segmented(
          choices.map((choice) => [String(choice), label(choice)]),
          (picked) => write(byText.get(picked)),
        );
        wrap = seg.element;
        sync = (value) => seg.set(String(value ?? setting.default));
      } else {
        control = el(
          'select',
          {
            class: 'control',
            'aria-label': text,
            onchange: (event) => write(byText.get(event.target.value)),
          },
          choices.map((choice) => el('option', { value: String(choice), text: label(choice) })),
        );
        wrap = control;
        sync = (value) => { control.value = String(value ?? setting.default); };
      }
    } else {
      // int or float: a number input, limited to the setting's bounds when it has them.
      const isInt = setting.type === 'int';
      const parse = (raw) => (isInt ? Math.round(Number(raw)) : Number(raw));
      const has = (bound) => bound !== null && bound !== undefined;
      let shown = setting.default;
      const props = {
        type: 'number',
        step: setting.step ?? (isInt ? 1 : 'any'),
        'aria-label': text,
        onchange: (event) => {
          if (event.target.value === '' || Number.isNaN(Number(event.target.value))) {
            control.value = String(shown);
            return;
          }
          let next = parse(event.target.value);
          if (setting.step) next = Math.round(next / setting.step) * setting.step;
          if (has(setting.min)) next = Math.max(setting.min, next);
          if (has(setting.max)) next = Math.min(setting.max, next);
          shown = next;
          control.value = String(next);
          write(next);
        },
      };
      if (has(setting.min)) props.min = setting.min;
      if (has(setting.max)) props.max = setting.max;
      control = el('input', props);
      wrap = control;
      sync = (value) => {
        shown = value ?? setting.default;
        control.value = String(shown);
      };
    }
    return { key: setting.key, element: field(text, wrap), sync };
  }

  return { element, update };
}

const entryOf = (cfg, id) => {
  const entry = (cfg.overlays[id] ??= {});
  entry.settings ??= {};
  return entry;
};

function field(text, control) {
  return el('div', { class: 'field' }, el('span', { class: 'field-label', text }), control);
}

/** A row of mutually exclusive buttons. `set` marks the one whose value matches. */
function segmented(options, onPick) {
  const pairs = options.map(([value, text]) => [
    value,
    el('button', { type: 'button', class: 'seg', text, onclick: () => onPick(value) }),
  ]);
  const element = el('div', { class: 'segmented', role: 'group' }, pairs.map(([, button]) => button));
  return {
    element,
    set(value) {
      for (const [option, button] of pairs) {
        const on = option === value;
        button.classList.toggle('on', on);
        button.setAttribute('aria-pressed', String(on));
      }
    },
  };
}
