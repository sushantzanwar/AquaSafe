/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        aqua: {
          50: "#eefcff",
          100: "#d6f6ff",
          200: "#b3ecff",
          300: "#7edcff",
          400: "#3ac5ff",
          500: "#0aa8f0",
          600: "#0084cc",
          700: "#0369a5",
          800: "#095887",
          900: "#0d4a70",
        },
      },
    },
  },
  plugins: [],
};
