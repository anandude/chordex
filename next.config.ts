import type { NextConfig } from "next";

// NEXT_OUTPUT=export builds a static site (Cloudflare Pages, see
// public/_redirects); unset keeps the normal server build (dev, Vercel).
const staticExport = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  // keep the floating Next.js dev badge out of the way (and out of screenshots)
  devIndicators: false,
  // In the server build the upload page moved to "/", so old /upload URLs need
  // a redirect. With output: export Next ignores this, and public/_redirects
  // does the same job at the edge.
  ...(staticExport
    ? { output: "export" as const, images: { unoptimized: true } }
    : {
        async redirects() {
          return [{ source: "/upload", destination: "/", permanent: true }];
        },
      }),
};

export default nextConfig;
