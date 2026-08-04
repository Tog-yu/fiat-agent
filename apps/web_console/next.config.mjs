/** @type {import('next').NextConfig} */
// Proxy the backend's /api/* under the same origin so the browser can call
// "/api/users/me" during dev without CORS. Override with FIAT_API_BASE.
const BACKEND = process.env.FIAT_API_BASE || "http://127.0.0.1:8000";

const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
    ];
  },
};

export default nextConfig;
