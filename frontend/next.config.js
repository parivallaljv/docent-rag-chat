/** @type {import('next').NextConfig} */

// Conservative response headers. No CSP yet: the app talks to Supabase (HTTPS +
// WebSocket) and the Render API and loads Google Fonts, so a CSP needs to be
// introduced in report-only mode first.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
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
