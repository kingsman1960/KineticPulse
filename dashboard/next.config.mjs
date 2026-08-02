/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false,
    serverComponentsExternalPackages: ["better-sqlite3"]
  }
};

export default nextConfig;
