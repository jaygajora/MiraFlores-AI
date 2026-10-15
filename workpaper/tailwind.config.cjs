/** Tailwind theme for the workpaper.
 *
 * Provenance is the visual system, so color only ever means evidence state:
 *   evidence (blue)  a link to evidence        verified (green) checked by a person
 *   recalc (teal)    recalculated independently adjusted (violet) changed by the workpaper
 *   error (red)      an error                  warning (amber)  needs attention
 * Each color is a CSS variable holding "R G B" channels (see web/styles.css), so
 * light and dark themes swap in one place and opacity modifiers (bg-evidence/20) work.
 */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const names = ["ground", "surface", "sunk", "ink", "muted", "rule", "rule-soft", "evidence", "evidence-tint", "verified", "recalc",
  "adjusted", "adjusted-tint", "error", "error-tint", "warning", "warning-tint", "page", "page-edge", "on-accent"];

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./web/src/**/*.{ts,tsx}", "./static/index.html"],
  theme: {
    extend: {
      colors: Object.fromEntries(names.map((n) => [n, token(n)])),
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        cond: ["IBM Plex Sans Condensed", "Arial Narrow", "IBM Plex Sans", "system-ui", "sans-serif"],
        serif: ["IBM Plex Serif", "Georgia", "serif"],
      },
      fontSize: { "2xs": ["11px", "1.3"], xs: ["12px", "1.4"], sm: ["13px", "1.45"], base: ["14px", "1.45"] },
      borderRadius: { DEFAULT: "4px" },
      boxShadow: { pop: "0 8px 24px rgb(20 30 40 / 0.18)", modal: "0 20px 50px rgb(0 0 0 / 0.3)", paper: "3px 3px 0 rgb(var(--page-edge) / 0.55)" },
      maxWidth: { prose: "78ch" },
    },
  },
  plugins: [],
};
