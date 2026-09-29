// Presentation helper installed as `window.__abDemo` by browser-automation `run_script`
// whenever a script mentions `__abDemo`. Evaluated as a function of the helper version.
// Actions dispatch script (untrusted) DOM events; overlays never receive pointer events.
(version) => {
  if (window.__abDemo && window.__abDemo.version === version) {
    return { installed: false, version };
  }
  const ROOT_ID = '__ab-demo-root';
  const Z_TOP = '2147483647';
  const TARGET_KEYS = new Set(['text', 'selector', 'nth']);
  const INTERACTIVE_SELECTOR = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary', 'label', '[contenteditable=""]',
    '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])', '[role="button"]', '[role="link"]',
    '[role="menuitem"]', '[role="tab"]', '[role="option"]', '[role="checkbox"]', '[role="radio"]',
    '[role="switch"]', '[role="combobox"]', '[role="textbox"]', '[role="treeitem"]',
  ].join(',');
  const state = { presentation: true, cursor: null, x: null, y: null };

  document.getElementById(ROOT_ID)?.remove();

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalizeText = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
  const ok = (action, extra = {}) => ({ ok: true, action, ...extra });
  const fail = (action, code, message, extra = {}) => ({ ok: false, action, error: { code, message, ...extra } });

  class HelperError extends Error {
    constructor(code, message, extra = {}) {
      super(message);
      this.code = code;
      this.extra = extra;
    }
  }

  function overlayRoot() {
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement('div');
      root.id = ROOT_ID;
      Object.assign(root.style, {
        position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: Z_TOP, overflow: 'hidden',
      });
      (document.body || document.documentElement).appendChild(root);
    }
    return root;
  }

  function overlayElement(tag, style) {
    const element = document.createElement(tag);
    Object.assign(element.style, { position: 'fixed', pointerEvents: 'none', ...style });
    overlayRoot().appendChild(element);
    return element;
  }

  // ---- target resolution -------------------------------------------------------------------

  function describeTarget(target) {
    if (!target || typeof target !== 'object') return typeof target === 'string' ? target : null;
    const copy = {};
    for (const key of ['text', 'selector', 'nth']) if (key in target) copy[key] = target[key];
    return copy;
  }

  function validateTarget(target) {
    if (!target || typeof target !== 'object' || Array.isArray(target)) {
      throw new HelperError('INVALID_TARGET', 'Target must be an object: {text} or {selector}, with optional nth.');
    }
    const keys = Object.keys(target);
    const hasText = typeof target.text === 'string' && target.text.trim() !== '';
    const hasSelector = typeof target.selector === 'string' && target.selector.trim() !== '';
    if (keys.some((key) => !TARGET_KEYS.has(key)) || hasText === hasSelector) {
      throw new HelperError('INVALID_TARGET', 'Target must have exactly one of text or selector (plus optional nth).');
    }
    if ('nth' in target && !(Number.isInteger(target.nth) && target.nth >= 0)) {
      throw new HelperError('INVALID_TARGET', 'nth must be a non-negative integer.');
    }
  }

  function isVisible(element) {
    if (!(element instanceof Element) || element.closest(`#${ROOT_ID}`)) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    return typeof element.checkVisibility === 'function' ? element.checkVisibility() : true;
  }

  const isDisabled = (element) => element.disabled === true || element.getAttribute('aria-disabled') === 'true';

  function textMatches(element, text) {
    return normalizeText(element.textContent) === text
      || normalizeText(element.getAttribute('aria-label')) === text
      || ((element instanceof HTMLInputElement || element instanceof HTMLButtonElement)
        && normalizeText(element.value) === text);
  }

  function findMatches(target, { requireEnabled }) {
    const usable = (element) => isVisible(element) && !(requireEnabled && isDisabled(element));
    if (target.selector) {
      try {
        return Array.from(document.querySelectorAll(target.selector)).filter(usable);
      } catch {
        throw new HelperError('INVALID_TARGET', `Invalid CSS selector: ${target.selector}`);
      }
    }
    const text = normalizeText(target.text);
    return Array.from(document.querySelectorAll('body *')).filter((element) => textMatches(element, text) && usable(element));
  }

  // Text targets: prefer interactive elements, and drop ancestors that match only because they
  // wrap a matching descendant. Selector targets are taken as selected.
  function narrow(target, elements) {
    if (target.selector) return elements;
    const interactive = elements.filter((element) => element.matches(INTERACTIVE_SELECTOR));
    const pool = interactive.length > 0 ? interactive : elements;
    return pool.filter((element) => !pool.some((other) => other !== element && element.contains(other)));
  }

  function findCandidates(target, { requireEnabled }) {
    return narrow(target, findMatches(target, { requireEnabled }));
  }

  function inViewport(element) {
    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    return x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
  }

  function scrollPositions(element) {
    const positions = [];
    for (let node = element.parentElement; node; node = node.parentElement) {
      if (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth) {
        positions.push([node, node.scrollLeft, node.scrollTop]);
      }
    }
    positions.push([null, window.scrollX, window.scrollY]);
    return positions;
  }

  function restoreScrollPositions(positions) {
    for (const [node, left, top] of positions) {
      if (node) {
        node.scrollLeft = left;
        node.scrollTop = top;
      } else {
        window.scrollTo({ left, top, behavior: 'instant' });
      }
    }
  }

  // Actionable like for a person: the topmost element at the target's center (after scrolling it
  // into view) is the target or inside it. Off-screen targets are scrolled and restored within this
  // synchronous task, so nothing visibly moves. Overlays of this helper never hit-test.
  function hitTest(element) {
    const positions = inViewport(element) ? null : scrollPositions(element);
    if (positions) element.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
    const point = targetPoint(element);
    const hit = document.elementFromPoint(point.x, point.y);
    if (positions) restoreScrollPositions(positions);
    return hit && (hit === element || element.contains(hit)) ? { ok: true } : { ok: false, cover: hit };
  }

  function candidateSummary(element) {
    const summary = { tag: element.tagName.toLowerCase(), text: normalizeText(element.textContent).slice(0, 80) };
    if (element.id) summary.id = element.id;
    return summary;
  }

  function resolveTarget(target, { requireEnabled = true, actionable = true } = {}) {
    validateTarget(target);
    const matches = findMatches(target, { requireEnabled });
    if (matches.length === 0) {
      throw new HelperError('NOT_FOUND', 'No visible element matches the target.');
    }
    let candidates;
    if (actionable) {
      const tested = matches.map((element) => ({ element, result: hitTest(element) }));
      candidates = narrow(target, tested.filter((entry) => entry.result.ok).map((entry) => entry.element));
      if (candidates.length === 0) {
        const cover = tested.find((entry) => entry.result.cover)?.result.cover;
        throw new HelperError('OBSCURED', 'Matching elements are covered by another element (for example an open popup or modal).', {
          ...(cover ? { covering: candidateSummary(cover) } : {}),
        });
      }
    } else {
      candidates = narrow(target, matches);
    }
    if ('nth' in target) {
      if (target.nth >= candidates.length) {
        throw new HelperError('NOT_FOUND', `nth ${target.nth} is out of range for ${candidates.length} matches.`);
      }
      return candidates[target.nth];
    }
    if (candidates.length > 1) {
      throw new HelperError('AMBIGUOUS', `${candidates.length} elements match; add nth or use a selector.`, {
        candidates: candidates.slice(0, 10).map(candidateSummary),
      });
    }
    return candidates[0];
  }

  // ---- presentation overlays ------------------------------------------------------------------

  function cursorElement() {
    if (state.cursor && state.cursor.isConnected) return state.cursor;
    const svgNs = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('width', '28');
    svg.setAttribute('height', '28');
    svg.setAttribute('viewBox', '0 0 28 28');
    const path = document.createElementNS(svgNs, 'path');
    path.setAttribute('d', 'M3 2 L3 22 L8.5 16.8 L12.2 25 L15.8 23.4 L12.2 15.4 L20 15.4 Z');
    path.setAttribute('fill', '#111827');
    path.setAttribute('stroke', '#ffffff');
    path.setAttribute('stroke-width', '1.6');
    path.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(path);
    const cursor = overlayElement('div', {
      left: '0', top: '0', width: '28px', height: '28px', marginLeft: '-3px', marginTop: '-2px',
      filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.35))', transitionProperty: 'transform',
      transitionTimingFunction: 'cubic-bezier(0.22, 0.61, 0.36, 1)', willChange: 'transform',
    });
    cursor.dataset.abDemo = 'cursor';
    cursor.appendChild(svg);
    state.cursor = cursor;
    if (state.x === null) {
      state.x = Math.round(window.innerWidth / 2);
      state.y = Math.round(window.innerHeight / 2);
    }
    cursor.style.transitionDuration = '0ms';
    cursor.style.transform = `translate(${state.x}px, ${state.y}px)`;
    return cursor;
  }

  function targetPoint(element) {
    const rect = element.getBoundingClientRect();
    const x = Math.min(Math.max(rect.left + rect.width / 2, 1), window.innerWidth - 2);
    const y = Math.min(Math.max(rect.top + rect.height / 2, 1), window.innerHeight - 2);
    return { x: Math.round(x), y: Math.round(y) };
  }

  async function bringIntoView(element) {
    const rect = element.getBoundingClientRect();
    if (rect.top >= 0 && rect.left >= 0 && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth) return;
    element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: state.presentation ? 'smooth' : 'auto' });
    await sleep(state.presentation ? 450 : 0);
  }

  async function moveCursorTo(point) {
    if (!state.presentation) {
      state.x = point.x;
      state.y = point.y;
      return;
    }
    const cursor = cursorElement();
    const distance = Math.hypot(point.x - state.x, point.y - state.y);
    const duration = Math.round(Math.min(900, Math.max(250, distance * 0.9)));
    // Force the start position to be committed before the transition begins.
    void cursor.getBoundingClientRect();
    cursor.style.transitionDuration = `${duration}ms`;
    cursor.style.transform = `translate(${point.x}px, ${point.y}px)`;
    state.x = point.x;
    state.y = point.y;
    await sleep(duration + 40);
  }

  function showClickIndicator(point) {
    if (!state.presentation) return;
    const ring = overlayElement('div', {
      left: `${point.x - 18}px`, top: `${point.y - 18}px`, width: '36px', height: '36px', borderRadius: '50%',
      border: '3px solid rgba(59,130,246,0.9)', background: 'rgba(59,130,246,0.18)', transform: 'scale(0.4)',
      opacity: '1', transition: 'transform 420ms ease-out, opacity 420ms ease-out',
    });
    ring.dataset.abDemo = 'click';
    void ring.getBoundingClientRect();
    ring.style.transform = 'scale(1.35)';
    ring.style.opacity = '0';
    setTimeout(() => ring.remove(), 600);
  }

  // ---- event dispatch ---------------------------------------------------------------------------

  function pointerInit(point, extra = {}) {
    return {
      bubbles: true, cancelable: true, composed: true, view: window,
      clientX: point.x, clientY: point.y, screenX: point.x, screenY: point.y, ...extra,
    };
  }

  function dispatchHover(element, point) {
    element.dispatchEvent(new PointerEvent('pointerover', pointerInit(point, { pointerType: 'mouse' })));
    element.dispatchEvent(new PointerEvent('pointerenter', { ...pointerInit(point, { pointerType: 'mouse' }), bubbles: false }));
    element.dispatchEvent(new MouseEvent('mouseover', pointerInit(point)));
    element.dispatchEvent(new MouseEvent('mouseenter', { ...pointerInit(point), bubbles: false }));
    element.dispatchEvent(new PointerEvent('pointermove', pointerInit(point, { pointerType: 'mouse' })));
    element.dispatchEvent(new MouseEvent('mousemove', pointerInit(point)));
  }

  function dispatchClick(element, point) {
    const pointer = pointerInit(point, { pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1 });
    element.dispatchEvent(new PointerEvent('pointerdown', pointer));
    element.dispatchEvent(new MouseEvent('mousedown', pointerInit(point, { button: 0, buttons: 1, detail: 1 })));
    if (typeof element.focus === 'function' && element.matches(INTERACTIVE_SELECTOR)) element.focus({ preventScroll: true });
    element.dispatchEvent(new PointerEvent('pointerup', { ...pointer, buttons: 0 }));
    element.dispatchEvent(new MouseEvent('mouseup', pointerInit(point, { button: 0, buttons: 0, detail: 1 })));
    element.dispatchEvent(new MouseEvent('click', pointerInit(point, { button: 0, buttons: 0, detail: 1 })));
  }

  const KEY_CODES = {
    Enter: 13, Escape: 27, Tab: 9, Backspace: 8, Delete: 46, ' ': 32, ArrowUp: 38, ArrowDown: 40,
    ArrowLeft: 37, ArrowRight: 39, Home: 36, End: 35, PageUp: 33, PageDown: 34,
  };

  function keyInit(key, modifiers) {
    const single = key.length === 1;
    const code = single ? (/[a-z]/i.test(key) ? `Key${key.toUpperCase()}` : /[0-9]/.test(key) ? `Digit${key}` : '') : key;
    const keyCode = KEY_CODES[key] ?? (single ? key.toUpperCase().charCodeAt(0) : 0);
    return {
      key, code, keyCode, which: keyCode, bubbles: true, cancelable: true, composed: true,
      metaKey: Boolean(modifiers.meta), ctrlKey: Boolean(modifiers.ctrl),
      altKey: Boolean(modifiers.alt), shiftKey: Boolean(modifiers.shift),
    };
  }

  function editableKind(element) {
    if (element instanceof HTMLTextAreaElement) return 'textarea';
    if (element instanceof HTMLInputElement) {
      const nonText = ['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit'];
      return nonText.includes(element.type) || element.readOnly || element.disabled ? null : 'input';
    }
    return element.isContentEditable ? 'contenteditable' : null;
  }

  function setNativeValue(element, value) {
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
  }

  // ---- public actions ---------------------------------------------------------------------------

  async function run(action, target, body) {
    try {
      return await body();
    } catch (error) {
      if (error instanceof HelperError) {
        return fail(action, error.code, error.message, { ...error.extra, ...(target !== undefined ? { target: describeTarget(target) } : {}) });
      }
      throw error;
    }
  }

  async function approach(target) {
    const element = resolveTarget(target);
    await bringIntoView(element);
    const point = targetPoint(element);
    await moveCursorTo(point);
    return { element, point };
  }

  // A real pointer event goes to the topmost element under the cursor: the target or its descendant.
  function pointerTarget(element, point) {
    const hit = document.elementFromPoint(point.x, point.y);
    return hit && element.contains(hit) ? hit : element;
  }

  const api = {
    version,

    click: (target) => run('click', target, async () => {
      const { element, point } = await approach(target);
      showClickIndicator(point);
      dispatchClick(pointerTarget(element, point), point);
      await sleep(state.presentation ? 180 : 0);
      return ok('click', { target: describeTarget(target) });
    }),

    hover: (target) => run('hover', target, async () => {
      const { element, point } = await approach(target);
      dispatchHover(pointerTarget(element, point), point);
      return ok('hover', { target: describeTarget(target) });
    }),

    type: (target, text, options = {}) => run('type', target, async () => {
      if (typeof text !== 'string') throw new HelperError('INVALID_TARGET', 'text to type must be a string.');
      const { element, point } = await approach(target);
      const kind = editableKind(element);
      if (!kind) throw new HelperError('NOT_EDITABLE', 'The target element is not an editable text field.');
      showClickIndicator(point);
      dispatchClick(element, point);
      element.focus({ preventScroll: true });
      const delayMs = state.presentation ? Math.max(0, Number(options.delayMs ?? 60)) : 0;
      const clear = options.clear !== false;
      if (kind === 'contenteditable') {
        if (clear) {
          document.execCommand('selectAll', false);
          document.execCommand('delete', false);
        }
        for (const character of text) {
          document.execCommand('insertText', false, character);
          if (delayMs) await sleep(delayMs);
        }
      } else {
        let value = clear ? '' : element.value;
        if (clear && element.value !== '') {
          setNativeValue(element, '');
          element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
        }
        for (const character of text) {
          value += character;
          setNativeValue(element, value);
          element.dispatchEvent(new InputEvent('input', { bubbles: true, data: character, inputType: 'insertText' }));
          if (delayMs) await sleep(delayMs);
        }
        element.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return ok('type', { target: describeTarget(target), length: text.length });
    }),

    press: (key, modifiers = {}) => run('press', undefined, async () => {
      if (typeof key !== 'string' || key === '') throw new HelperError('INVALID_TARGET', 'key must be a non-empty string such as "Enter" or "k".');
      const element = document.activeElement || document.body;
      const init = keyInit(key, modifiers);
      element.dispatchEvent(new KeyboardEvent('keydown', init));
      element.dispatchEvent(new KeyboardEvent('keyup', init));
      await sleep(state.presentation ? 120 : 0);
      return ok('press', { key, modifiers: { meta: init.metaKey, ctrl: init.ctrlKey, alt: init.altKey, shift: init.shiftKey } });
    }),

    scroll: (target, delta = {}) => run('scroll', target ?? undefined, async () => {
      const left = Number(delta.x ?? 0);
      const top = Number(delta.y ?? 0);
      const behavior = state.presentation ? 'smooth' : 'auto';
      if (target === null || target === undefined) {
        window.scrollBy({ left, top, behavior });
      } else {
        const { element } = await approach(target);
        element.scrollBy({ left, top, behavior });
      }
      await sleep(state.presentation ? 500 : 0);
      return ok('scroll', { ...(target ? { target: describeTarget(target) } : {}), x: left, y: top });
    }),

    select: (target, choice = {}) => run('select', target, async () => {
      const { element, point } = await approach(target);
      if (!(element instanceof HTMLSelectElement)) throw new HelperError('NOT_EDITABLE', 'The target element is not a <select>.');
      const options = Array.from(element.options);
      const index = 'index' in choice ? Number(choice.index)
        : 'value' in choice ? options.findIndex((option) => option.value === String(choice.value))
          : 'label' in choice ? options.findIndex((option) => normalizeText(option.label) === normalizeText(choice.label))
            : -1;
      if (!(index >= 0 && index < options.length)) throw new HelperError('NOT_FOUND', 'No option matches {label|value|index}.');
      showClickIndicator(point);
      element.focus({ preventScroll: true });
      element.selectedIndex = index;
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return ok('select', { target: describeTarget(target), value: element.value, label: options[index].label });
    }),

    waitFor: (target, options = {}) => run('waitFor', target, async () => {
      validateTarget(target);
      const timeoutMs = Math.max(0, Number(options.timeoutMs ?? 10000));
      const wantHidden = options.state === 'hidden';
      const deadline = Date.now() + timeoutMs;
      while (true) {
        const count = findCandidates(target, { requireEnabled: false }).length;
        if (wantHidden ? count === 0 : count > 0) {
          return ok('waitFor', { target: describeTarget(target), state: wantHidden ? 'hidden' : 'visible', count });
        }
        if (Date.now() >= deadline) {
          throw new HelperError('TIMEOUT', `Target did not become ${wantHidden ? 'hidden' : 'visible'} within ${timeoutMs} ms.`);
        }
        await sleep(100);
      }
    }),

    caption: (text, options = {}) => run('caption', undefined, async () => {
      if (typeof text !== 'string' || text.trim() === '') throw new HelperError('INVALID_TARGET', 'caption text must be a non-empty string.');
      api.hideCaption();
      const position = options.position === 'top' ? 'top' : 'bottom';
      const caption = overlayElement('div', {
        left: '50%', [position]: '6%', transform: 'translateX(-50%)', maxWidth: '80%', padding: '12px 22px',
        borderRadius: '12px', background: 'rgba(17,24,39,0.88)', color: '#ffffff', fontSize: '22px',
        lineHeight: '1.35', fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif', fontWeight: '500',
        textAlign: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
      });
      caption.dataset.abDemo = 'caption';
      caption.textContent = text;
      return ok('caption', { text, position });
    }),

    hideCaption: () => {
      const root = document.getElementById(ROOT_ID);
      root?.querySelectorAll('[data-ab-demo="caption"]').forEach((element) => element.remove());
      return ok('hideCaption');
    },

    highlight: (target, options = {}) => run('highlight', target, async () => {
      const element = resolveTarget(target, { requireEnabled: false, actionable: false });
      await bringIntoView(element);
      const rect = element.getBoundingClientRect();
      const box = overlayElement('div', {
        left: `${rect.left - 6}px`, top: `${rect.top - 6}px`, width: `${rect.width + 12}px`, height: `${rect.height + 12}px`,
        borderRadius: '10px', border: '3px solid rgba(245,158,11,0.95)', boxShadow: '0 0 0 6px rgba(245,158,11,0.25)',
      });
      box.dataset.abDemo = 'highlight';
      const durationMs = Math.max(0, Number(options.durationMs ?? 1500));
      setTimeout(() => box.remove(), durationMs);
      return ok('highlight', { target: describeTarget(target), durationMs });
    }),

    setPresentation: (enabled) => {
      state.presentation = Boolean(enabled);
      if (!state.presentation) {
        document.getElementById(ROOT_ID)?.remove();
        state.cursor = null;
      }
      return ok('setPresentation', { presentation: state.presentation });
    },

    status: () => ({ installed: true, version, presentation: state.presentation }),
  };

  Object.defineProperty(window, '__abDemo', { value: Object.freeze(api), configurable: true, writable: true });
  return { installed: true, version };
}
