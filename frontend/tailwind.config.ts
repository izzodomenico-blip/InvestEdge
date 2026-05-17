import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070B13",
          900: "#0B1020",
          850: "#0F172A",
          800: "#111827",
          700: "#1F2937",
        },
        edge: {
          cyan: "#22D3EE",
          green: "#34D399",
          amber: "#F59E0B",
          rose: "#FB7185",
          blue: "#60A5FA",
        },
      },
      boxShadow: {
        panel: "0 20px 60px rgba(0, 0, 0, 0.28)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
