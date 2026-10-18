import type { NextConfig } from "next";

// NEXT_OUTPUT=export builds a static site (Cloudflare Pages, see
// public/_redirects); unset keeps the normal server build (dev, Vercel).
const staticExport = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  // keep the floating Next.js dev badge out of the way (and out of screenshots)
  devIndicators: false,
  ...(staticExport && { output: "export", images: { unoptimized: true } }),
};

export default nextConfig;
