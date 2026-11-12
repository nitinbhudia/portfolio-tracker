import type { NextConfig } from "next";

// The browser only talks to Next.js; /api/* is proxied to the local FastAPI backend (port 8001).
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  experimental: { proxyTimeout: 120_000 }, // importing a large workbook and fetching ECB rates can take a while
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      // Research (the former Fibonacci AI app) has its own API, mounted under /research in the same backend.
      { source: "/research/api/:path*", destination: `${backend}/research/api/:path*` },
    ];
  },
};

export default nextConfig;
