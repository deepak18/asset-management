import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

/**
 * ESLint 9 flat config. Next 16's `eslint-config-next` ships ready-made flat
 * config arrays (`core-web-vitals`, `typescript`), so we spread them directly
 * rather than bridging legacy "extends" through FlatCompat.
 */
const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // Strong typing is a hard project rule (§8) — never silently allow `any`.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": "warn",
    },
  },
  {
    // Generated files owned by tools, not hand-edited: contract types
    // (openapi-typescript) and the MSW service worker.
    ignores: [
      "src/types/api.ts",
      "public/mockServiceWorker.js",
      ".next/**",
      "node_modules/**",
    ],
  },
];

export default eslintConfig;
