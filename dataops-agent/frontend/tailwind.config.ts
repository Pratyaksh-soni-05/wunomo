import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        gray: { 950: "#0a0a0f", 925: "#0f0f14", 900: "#111118" },
      },
    },
  },
  plugins: [],
};

export default config;
