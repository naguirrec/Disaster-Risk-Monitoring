import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Opened at 127.0.0.1. Next treats that host as cross-origin against
  // localhost and would block the client bundles, so the map and the
  // segmentation request never start.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
