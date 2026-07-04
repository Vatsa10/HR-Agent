import type { NextConfig } from "next";

// Proxy API to the FastAPI backend so the browser stays same-origin
// (session cookie flows without CORS). Override with API_ORIGIN in prod.
const API_ORIGIN = process.env.API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
