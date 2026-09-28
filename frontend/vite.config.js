import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Runs on Vite's default port 5173 -- this is the exact origin the FastAPI
// backend's CORS settings (main.py) allow, with credentials (cookies) on.
export default defineConfig({
  plugins: [react()],
});
