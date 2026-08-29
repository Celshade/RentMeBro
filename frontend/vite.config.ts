import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Env vars every build must have; neither has a safe fallback. */
const REQUIRED_ENV_VARS = [
  "VITE_API_BASE_URL",
  "VITE_STRIPE_PUBLISHABLE_KEY",
] as const;

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  if (command === "build") {
    const env = loadEnv(mode, process.cwd(), "VITE_");
    const missing = REQUIRED_ENV_VARS.filter((key) => !env[key]);
    if (missing.length > 0) {
      throw new Error(
        `Missing required env var(s) for production build: ` +
          `${missing.join(", ")}. Without these the bundle would ship ` +
          `with undefined API/Stripe endpoints.`,
      );
    }
  }

  return {
    plugins: [react()],
  };
});
