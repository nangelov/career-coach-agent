import type { NextConfig } from "next";
import { buildApiRewrites } from "./lib/apiProxy";

const nextConfig: NextConfig = {
  // Same-origin API proxy: forward browser calls to /api/** to the FastAPI
  // backend (app-design §9 mounts the v2 API under /api). The browser only ever
  // talks to the Next.js origin, so this avoids CORS and keeps the backend host
  // out of the client bundle.
  //
  // This runs in EVERY environment (dev and production `next start`), because
  // the docker-compose deployment runs frontend and backend as two separate
  // origins with no reverse proxy in front — without this rewrite, /api/* calls
  // 404 inside the Next.js server (FIX-05). The backend host is parameterized by
  // INTERNAL_API_URL (default http://localhost:8000; docker-compose sets
  // http://backend:8000). See lib/apiProxy.ts.
  async rewrites() {
    return buildApiRewrites();
  },
};

export default nextConfig;
