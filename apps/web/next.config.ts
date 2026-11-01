import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // The dev server sits behind Caddy on these hosts. Dev only: production ignores this setting.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
