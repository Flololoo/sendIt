// DOM helpers. Server strings always enter the page as text nodes, never as markup.

/**
 * Create an element. `text` sets textContent. Other keys become properties when the element has
 * one of that name (value, checked, min, ...), otherwise attributes. `onclick`-style keys bind listeners.
 * Children may be nodes, strings, numbers, arrays or null/false (skipped).
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'text') node.textContent = String(value);
    else if (key === 'class') node.className = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key === 'for') node.htmlFor = value;
    else if (key in node && key !== 'style') node[key] = value;
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  const nodes = children
    .flat(Infinity)
    .filter((child) => child !== null && child !== undefined && child !== false)
    .map((child) => (child instanceof Node ? child : document.createTextNode(String(child))));
  node.append(...nodes);
  return node;
}

/** A notice body for an error: the message, then any detail lines the server sent with it. */
export function errorNode(error) {
  const details = error?.details ?? [];
  return el(
    'div',
    { class: 'error-box' },
    el('strong', { text: error?.message ?? String(error) }),
    details.length ? el('ul', {}, details.map((line) => el('li', { text: line }))) : null,
  );
}
