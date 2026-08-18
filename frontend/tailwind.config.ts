import type { Config } from "tailwindcss";

export default {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Verdana", "Tahoma", "Arial", "sans-serif"],
        heading: ["'Trebuchet MS'", "Impact", "Verdana", "sans-serif"],
        serif: ["'Times New Roman'", "Georgia", "serif"],
        mono: ["'Courier New'", "Courier", "monospace"],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        win98: {
          gray: "#c0c0c0",
          dark: "#808080",
          light: "#ffffff",
          navy: "#000080",
          teal: "#008080",
        },
      },
      animation: {
        blink: "blink 1s step-end infinite",
        "pulse-fast": "pulseFast 0.8s ease-in-out infinite",
        glitter: "glitter 3s linear infinite",
        marquee: "marquee 15s linear infinite",
      },
      keyframes: {
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        pulseFast: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.85", transform: "scale(1.02)" },
        },
        glitter: {
          "0%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
          "100%": { backgroundPosition: "0% 50%" },
        },
        marquee: {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(-100%)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
