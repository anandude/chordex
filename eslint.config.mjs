import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // The Next.js app sits at the repository root, which also holds the Python
    // backend, the deploy stack, the eval harness, and (after the root move) a
    // stale frontend/ build directory. Only app/, components/ and lib/ are
    // lintable source, so everything else is ignored explicitly — otherwise
    // `npm run lint` walks generated bundles inside those folders.
    "backend/**",
    "deploy/**",
    "docs/**",
    "eval/**",
    "public/**",
    "test-assets/**",
    "frontend/**",
  ]),
]);

export default eslintConfig;
