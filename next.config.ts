import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next blocks /_next dev assets unless the browser host is allowed. Without
  // those bundles MapLibre never starts, so the map stays blank. localhost is
  // built in; 127.0.0.1, the machine name and Cursor preview hosts are not.
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "cursor",
    "*.cursor.sh",
    "**.cursor.sh",
    "*.cursor.com",
    "**.cursor.com",
    "*.cursorvm.com",
    "**.cursorvm.com",
    "*.cursorvm.net",
    "**.cursorvm.net",
  ],
};

export default nextConfig;
