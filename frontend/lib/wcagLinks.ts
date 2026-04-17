/**
 * WCAG Understanding documentation links.
 *
 * Maps criterion numbers (e.g. "2.4.7") to their W3C Understanding page slugs.
 * Most slugs are derived from the criterion label (lowercase, spaces → hyphens,
 * parentheses stripped). Exceptions are hardcoded where the actual W3C slug
 * diverges from that pattern.
 *
 * URL pattern:
 *   WCAG 2.1 — https://www.w3.org/WAI/WCAG21/Understanding/<slug>.html
 *   WCAG 2.2 — https://www.w3.org/WAI/WCAG22/Understanding/<slug>.html
 *
 * Verified against W3C server on 2026-04-17.
 */

const SLUGS: Record<string, string> = {
  // 1 — Perceivable
  "1.1.1":  "non-text-content",
  "1.2.1":  "audio-only-and-video-only-prerecorded",   // label omits "-prerecorded"
  "1.2.2":  "captions-prerecorded",
  "1.2.3":  "audio-description-or-media-alternative-prerecorded",
  "1.3.1":  "info-and-relationships",
  "1.4.1":  "use-of-color",
  "1.4.3":  "contrast-minimum",
  "1.4.4":  "resize-text",
  "1.4.10": "reflow",

  // 2 — Operable
  "2.1.1":  "keyboard",
  "2.1.2":  "no-keyboard-trap",
  "2.2.2":  "pause-stop-hide",
  "2.3.1":  "three-flashes-or-below-threshold",        // label is just "Three Flashes"
  "2.4.1":  "bypass-blocks",
  "2.4.2":  "page-titled",
  "2.4.3":  "focus-order",
  "2.4.4":  "link-purpose-in-context",                 // "link-purpose" returns 404
  "2.4.7":  "focus-visible",
  "2.4.11": "focus-not-obscured-minimum",              // WCAG 2.2 only
  "2.4.12": "focus-not-obscured-enhanced",             // WCAG 2.2 only
  "2.4.13": "focus-appearance",                        // WCAG 2.2 only
  "2.5.5":  "target-size",
  "2.5.8":  "target-size-minimum",                     // WCAG 2.2 only

  // 3 — Understandable
  "3.1.1":  "language-of-page",
  "3.3.1":  "error-identification",
  "3.3.2":  "labels-or-instructions",
  "3.3.3":  "error-suggestion",
  "3.3.4":  "error-prevention-legal-financial-data",   // "error-prevention" returns 404

  // 4 — Robust
  "4.1.1":  "parsing",
  "4.1.2":  "name-role-value",
};

/** Criteria that only exist in WCAG 2.2 — always link to the WCAG22 path. */
const WCAG22_ONLY = new Set(["2.4.11", "2.4.12", "2.4.13", "2.5.8"]);

/**
 * Returns the W3C Understanding URL for a criterion, or null if unknown.
 * @param criterion  e.g. "2.4.7"
 * @param wcagVersion  "2.1" | "2.2" — the version the user selected
 */
export function getWcagUrl(criterion: string, wcagVersion: string): string | null {
  const slug = SLUGS[criterion];
  if (!slug) return null;
  const versionPath =
    wcagVersion === "2.2" || WCAG22_ONLY.has(criterion) ? "WCAG22" : "WCAG21";
  return `https://www.w3.org/WAI/${versionPath}/Understanding/${slug}.html`;
}
