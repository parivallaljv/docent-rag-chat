/** @type {import('next').NextConfig} */

// Conservative response headers. The CSP is report-only (not enforcing): the
// app talks to Supabase (HTTPS + WebSocket) and the Render API and loads
// Google Fonts. Next needs 'unsafe-inline'/'unsafe-eval' for scripts without nonces.
function originSources(url) {
  try {
    const { host } = new URL(url);
    return [`https://${host}`, `wss://${host}`];
  } catch {
    return [];
  }
}

const connectSrc = [
  "'self'",
  ...originSources(process.env.NEXT_PUBLIC_SUPABASE_URL || ""),
  ...originSources(process.env.NEXT_PUBLIC_API_URL || ""),
].join(" ");

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob:",
  `connect-src ${connectSrc}`,
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "Content-Security-Policy-Report-Only", value: csp },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Self-contained server bundle for the Docker image only; Vercel ignores it
  // unless set, so keep it opt-in.
  ...(process.env.DOCKER_BUILD ? { output: "standalone" } : {}),
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

module.exports = nextConfig;
