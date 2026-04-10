"use client";

import { useWcagVersion } from "./WcagVersionProvider";

export default function HeaderVersion() {
  const { version } = useWcagVersion();
  return (
    <span className="text-xs mt-0.5 block" style={{ color: "var(--muted)" }}>
      WCAG {version} Level AA — Powered by OLMo3 &amp; Molmo2
    </span>
  );
}
