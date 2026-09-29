"""DOM snapshot page program and response normalization."""

from __future__ import annotations

from typing import Any, cast

from browser_automation.contracts import DomSnapshotElement

DOM_SNAPSHOT_SCRIPT = r"""
({ includeNonInteractive, includeBoundingBoxes, maxElements }) => {
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const cssEscape = (value) => {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  };
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) !== 0;
  };
  const buildSelector = (el) => {
    if (el.id) return `#${cssEscape(el.id)}`;
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === Node.ELEMENT_NODE && depth < 6) {
      let part = node.tagName.toLowerCase();
      if (node.classList && node.classList.length > 0) {
        const classes = Array.from(node.classList).slice(0, 2).map(cssEscape);
        if (classes.length > 0) part += `.${classes.join(".")}`;
      }
      let nth = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === node.tagName) nth += 1;
        sibling = sibling.previousElementSibling;
      }
      part += `:nth-of-type(${nth})`;
      parts.unshift(part);
      if (node.parentElement && node.parentElement.id) {
        parts.unshift(`#${cssEscape(node.parentElement.id)}`);
        break;
      }
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(" > ");
  };
  const interactiveSelector = [
    "a[href]", "button", "input", "select", "textarea", "summary",
    "[role='button']", "[role='link']", "[role='checkbox']", "[role='radio']",
    "[role='tab']", "[onclick]", "[contenteditable='']", "[contenteditable='true']", "[tabindex]"
  ].join(",");
  const candidates = Array.from(document.querySelectorAll(includeNonInteractive ? "*" : interactiveSelector));
  const elements = [];
  const seenSelectors = new Set();
  for (const el of candidates) {
    if (elements.length >= maxElements) break;
    if (!isVisible(el)) continue;
    const cssSelector = buildSelector(el);
    if (!cssSelector || seenSelectors.has(cssSelector)) continue;
    seenSelectors.add(cssSelector);
    const rect = el.getBoundingClientRect();
    const text = normalize(el.innerText || el.textContent).slice(0, 240) || null;
    const name = normalize(
      el.getAttribute("aria-label") || el.getAttribute("title") ||
      el.getAttribute("placeholder") || el.getAttribute("alt")
    ) || null;
    const value = "value" in el && typeof el.value === "string"
      ? normalize(el.value).slice(0, 240) || null : null;
    elements.push({
      element_id: `e${elements.length + 1}`,
      tag_name: el.tagName.toLowerCase(),
      dom_id: el.id || null,
      css_selector: cssSelector,
      role: el.getAttribute("role"),
      name,
      text,
      href: el.getAttribute("href") ? String(el.getAttribute("href")) : null,
      value,
      bounding_box: includeBoundingBoxes ? {
        x: Number(rect.x), y: Number(rect.y), width: Number(rect.width), height: Number(rect.height)
      } : null
    });
  }
  return {
    schema_version: "browser-dom-snapshot-v1",
    total_candidates: candidates.length,
    returned_elements: elements.length,
    truncated: candidates.length > elements.length,
    elements
  };
}
"""


def normalize_snapshot(raw: Any, *, max_elements: int) -> dict[str, Any]:
    snapshot = raw if isinstance(raw, dict) else {}
    raw_elements = snapshot.get("elements")
    elements = cast(list[DomSnapshotElement], raw_elements if isinstance(raw_elements, list) else [])
    total = snapshot.get("total_candidates")
    returned = snapshot.get("returned_elements")
    truncated = snapshot.get("truncated")
    return {
        "elements": elements,
        "total_candidates": total if isinstance(total, int) else len(elements),
        "returned_elements": returned if isinstance(returned, int) else len(elements),
        "truncated": truncated if isinstance(truncated, bool) else len(elements) >= max_elements,
    }
