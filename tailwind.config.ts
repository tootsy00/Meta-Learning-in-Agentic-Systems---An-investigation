import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#faf6ef",
        ink: "#2d2418",
      },
    },
  },
  plugins: [],
};

export default config;
