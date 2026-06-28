import type { Config } from "jest";
import nextJest from "next/jest.js";

// next/jest wires up the Next.js SWC transform (so .ts/.tsx test files compile
// without ts-jest/babel-jest), loads next.config + .env files, and applies the
// project's module aliases. `dir` points at the app root so that config loads.
const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  testEnvironment: "jest-environment-jsdom",
  // Loads @testing-library/jest-dom matchers (e.g. toBeInTheDocument) before tests.
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  // Mirror the tsconfig "@/*" path alias for Jest's module resolver.
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
};

// createJestConfig is async so Next can load the SWC config — export the promise.
export default createJestConfig(config);
