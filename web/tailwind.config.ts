import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

// Calm neutral palette (slate) + one accent (teal). Better/worse colours are always paired
// with a sign, an arrow and a word, so meaning never relies on colour alone.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: colors.slate,
        accent: colors.teal,
        better: colors.emerald,
        worse: colors.rose,
        caution: colors.amber,
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: {
        metric: ["2rem", { lineHeight: "2.375rem", fontWeight: "650" }],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.06), 0 1px 3px rgba(15,23,42,0.08)",
        drawer: "-8px 0 24px rgba(15,23,42,0.14)",
      },
      keyframes: {
        "slide-in": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        "slide-in": "slide-in 160ms ease-out",
        "fade-in": "fade-in 160ms ease-out",
      },
    },
  },
  plugins: [],
} satisfies Config;
