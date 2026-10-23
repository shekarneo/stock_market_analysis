/** @type {import('next').NextConfig} */
const apiUrl = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  experimental: {
    // A full multi-agent analysis with LLM agents can take over a minute; the default
    // rewrite proxy timeout (30s) cut it off and the page showed a 500.
    proxyTimeout: 180000,
  },
  async rewrites() {
    return [
      { source: "/health", destination: `${apiUrl}/health` },
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
    ];
  },
};

module.exports = nextConfig;
