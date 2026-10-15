/** Design tokens live in src/index.css as CSS variables; Tailwind only maps names to them. */
const v = (n) => `rgb(var(--${n}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: v("ink"), panel: v("panel"), raised: v("raised"), line: v("line"), "line-strong": v("line-strong"),
        fg: v("fg"), muted: v("muted"), faint: v("faint"),
        net: v("net"), safe: v("safe"), warn: v("warn"), bad: v("bad"),
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: { xs: ["12px", "16px"], sm: ["13px", "19px"], base: ["14px", "21px"], lg: ["16px", "24px"], xl: ["19px", "26px"], "2xl": ["24px", "30px"] },
      borderRadius: { DEFAULT: "4px", md: "6px", lg: "8px" },
    },
  },
  plugins: [],
};
