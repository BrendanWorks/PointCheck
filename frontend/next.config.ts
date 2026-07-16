import type { NextConfig } from "next";

// API origins the browser must reach: fetch + WebSocket, prod/staging/local.
const API_ORIGINS = [
  "https://brendanworks--wcag-tester-web.modal.run",
  "wss://brendanworks--wcag-tester-web.modal.run",
  "https://brendanworks-staging--wcag-tester-web.modal.run",
  "wss://brendanworks-staging--wcag-tester-web.modal.run",
  "http://localhost:8000",
  "ws://localhost:8000",
].join(" ");

const isDev = process.env.NODE_ENV === "development";

const csp = [
  "default-src 'self'",
  // 'unsafe-inline' is required by Next.js's inline bootstrap scripts and the
  // GA init snippet; 'unsafe-eval' is required by React Fast Refresh in dev.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""} https://*.googletagmanager.com`,
  "style-src 'self' 'unsafe-inline'",
  // data:/blob: for screenshot_b64 previews and the generated PDF download
  "img-src 'self' data: blob: https://*.google-analytics.com https://*.googletagmanager.com",
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGINS} https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
