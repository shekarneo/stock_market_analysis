/** @type {import('next').NextConfig} */
const apiUrl = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    return [
      { source: "/health", destination: `${apiUrl}/health` },
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
    ];
  },
};

module.exports = nextConfig;
