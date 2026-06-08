export default {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
        extend: {
            colors: {
                ink: {
                    975: "#04060B",
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
                    violet: "#A78BFA",
                    gold: "#E0B062",
                },
            },
            boxShadow: {
                panel: "0 30px 60px -30px rgba(2, 6, 23, 0.85), 0 0 0 1px rgba(148, 163, 184, 0.04)",
                glow: "0 0 28px -8px rgba(34, 211, 238, 0.55)",
                inset: "inset 0 1px 0 rgba(255, 255, 255, 0.04)",
            },
            fontFamily: {
                display: ['"Fraunces"', "ui-serif", "Georgia", "serif"],
                sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
                mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
            },
            letterSpacing: {
                eyebrow: "0.22em",
            },
            keyframes: {
                "fade-up": {
                    "0%": { opacity: "0", transform: "translateY(8px)" },
                    "100%": { opacity: "1", transform: "translateY(0)" },
                },
                "pulse-soft": {
                    "0%, 100%": { opacity: "0.45" },
                    "50%": { opacity: "1" },
                },
                shimmer: {
                    "0%": { backgroundPosition: "-200% 0" },
                    "100%": { backgroundPosition: "200% 0" },
                },
            },
            animation: {
                "fade-up": "fade-up 380ms cubic-bezier(0.22, 1, 0.36, 1) both",
                "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
                shimmer: "shimmer 1.8s linear infinite",
            },
            backgroundImage: {
                "noise": "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.045 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>\")",
                "halo-cyan": "radial-gradient(circle at 50% 0%, rgba(34, 211, 238, 0.16), transparent 60%)",
                "halo-violet": "radial-gradient(circle at 90% 0%, rgba(167, 139, 250, 0.14), transparent 55%)",
            },
        },
    },
    plugins: [],
};
