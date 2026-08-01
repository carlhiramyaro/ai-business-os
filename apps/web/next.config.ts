import type { NextConfig } from "next";

// v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]):
// the same header set apps/api/main.py's security_headers_middleware sets
// for the API, minus the API-only CSP -- a real CSP for this app needs
// nonce plumbing through Next's script tags and report-only iteration
// first, deliberately out of scope here.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
];

// Gated on production specifically: sending this from http://localhost
// pins the browser to HTTPS for "localhost" -- every other local project
// on that port, not just this one -- for a year, reversible only via
// chrome://net-internals/#hsts. Matches app/main.py's identical gate on
// ENVIRONMENT != "local".
if (process.env.NODE_ENV === "production") {
  securityHeaders.push({
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  });
}

const nextConfig: NextConfig = {
  // Emits .next/standalone -- a self-contained server bundle with only the
  // node_modules actually needed, instead of the full node_modules tree.
  // Docker's runner stage copies just this + .next/static + public, which
  // is the difference between a ~1GB and a ~200MB image. See
  // docs/infra-guide.md's "Next.js in Docker" section.
  output: "standalone",

  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
