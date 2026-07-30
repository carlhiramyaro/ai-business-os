import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone -- a self-contained server bundle with only the
  // node_modules actually needed, instead of the full node_modules tree.
  // Docker's runner stage copies just this + .next/static + public, which
  // is the difference between a ~1GB and a ~200MB image. See
  // docs/infra-guide.md's "Next.js in Docker" section.
  output: "standalone",
};

export default nextConfig;
