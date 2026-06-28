import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev-only API proxy: forward browser calls to /api/** to the FastAPI
  // backend (app-design §9 mounts the v2 API under /api). In production the
  // reverse proxy / single-container Dockerfile handles routing, so we only
  // rewrite during local development to avoid CORS and hard-coded hosts.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
