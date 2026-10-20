import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Arabic-first: the bare URL opens the Arabic dashboard.
  async redirects() {
    return [{ source: "/", destination: "/ar", permanent: false }];
  },
};

export default nextConfig;
