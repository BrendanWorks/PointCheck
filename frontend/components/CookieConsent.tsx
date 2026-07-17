"use client";

/**
 * Cookie-consent banner gating Google Analytics (GDPR-style opt-in).
 *
 * GA4 previously loaded unconditionally from layout.tsx. Now nothing
 * analytics-related touches the browser until the visitor accepts:
 * loadAnalytics() injects gtag.js and fires the initial config only after
 * an explicit "Accept". Decline stores the choice and loads nothing.
 * All analytics call sites already no-op when window.gtag is absent
 * (lib/analytics.ts, components/GoogleAnalytics.tsx), so declining
 * degrades silently.
 *
 * The footer's "Cookie preferences" button re-opens the banner via the
 * `pointcheck:open-cookie-prefs` window event so a choice is never final.
 */

import { useEffect, useState } from "react";

const CONSENT_KEY = "pointcheck_analytics_consent";
const REOPEN_EVENT = "pointcheck:open-cookie-prefs";

type Choice = "accepted" | "declined";

function loadAnalytics(measurementId: string) {
  if (document.getElementById("ga4-src")) return; // already injected
  const s = document.createElement("script");
  s.id = "ga4-src";
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`;
  document.head.appendChild(s);

  const w = window as unknown as { dataLayer?: unknown[]; gtag?: (...a: unknown[]) => void };
  w.dataLayer = w.dataLayer || [];
  w.gtag = function gtag(...args: unknown[]) {
    w.dataLayer!.push(args);
  };
  w.gtag("js", new Date());
  w.gtag("config", measurementId);
}

export function CookiePrefsButton({ className }: { className?: string }) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => window.dispatchEvent(new Event(REOPEN_EVENT))}
    >
      Cookie preferences
    </button>
  );
}

export default function CookieConsent({ measurementId }: { measurementId: string }) {
  // null until mounted — avoids SSR/localStorage mismatch flicker
  const [choice, setChoice] = useState<Choice | null | "unset">(null);
  const [forceOpen, setForceOpen] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_KEY) as Choice | null;
    // Persisted consent can only be read after mount (SSR has no localStorage).
    // A lazy useState initializer would read it during render and cause a
    // hydration mismatch, so this deliberate post-mount setState is the
    // SSR-safe pattern here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChoice(stored ?? "unset");
    if (stored === "accepted") loadAnalytics(measurementId);
  }, [measurementId]);

  useEffect(() => {
    const reopen = () => setForceOpen(true);
    window.addEventListener(REOPEN_EVENT, reopen);
    return () => window.removeEventListener(REOPEN_EVENT, reopen);
  }, []);

  const decide = (value: Choice) => {
    localStorage.setItem(CONSENT_KEY, value);
    setChoice(value);
    setForceOpen(false);
    if (value === "accepted") loadAnalytics(measurementId);
    // Declining after a previous accept: gtag stays for this page view but
    // the stored choice stops it on every subsequent load.
  };

  const open = choice === "unset" || forceOpen;
  if (choice === null || !open) return null;

  return (
    <div
      className="fixed bottom-0 inset-x-0 z-50"
      style={{
        background: "var(--surface)",
        borderTop: "1px solid var(--border)",
      }}
    >
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-3 sm:py-4 flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
        <p className="text-xs sm:text-sm flex-1" style={{ color: "var(--muted)" }}>
          We use Google Analytics to understand site usage — page views and
          audit activity, including the URL you test. Decline and everything
          still works, with no analytics loaded.{" "}
          <a href="/privacy" className="underline" style={{ color: "var(--lime)" }}>
            Privacy Policy
          </a>
          .
        </p>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => decide("declined")}
            className="px-4 py-2 text-sm rounded-lg transition-colors cursor-pointer"
            style={{
              background: "var(--surface2)",
              border: "1px solid var(--border)",
              color: "var(--muted)",
            }}
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => decide("accepted")}
            className="px-4 py-2 text-sm font-semibold rounded-lg transition-opacity hover:opacity-90 cursor-pointer"
            style={{ background: "var(--lime)", color: "#0A0A0B" }}
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
