declare const _default: {
    content: string[];
    theme: {
        extend: {
            colors: {
                ink: {
                    975: string;
                    950: string;
                    900: string;
                    850: string;
                    800: string;
                    700: string;
                };
                edge: {
                    cyan: string;
                    green: string;
                    amber: string;
                    rose: string;
                    blue: string;
                    violet: string;
                    gold: string;
                };
            };
            boxShadow: {
                panel: string;
                glow: string;
                inset: string;
            };
            fontFamily: {
                display: [string, string, string, string];
                sans: [string, string, string, string];
                mono: [string, string, string, string];
            };
            letterSpacing: {
                eyebrow: string;
            };
            keyframes: {
                "fade-up": {
                    "0%": {
                        opacity: string;
                        transform: string;
                    };
                    "100%": {
                        opacity: string;
                        transform: string;
                    };
                };
                "pulse-soft": {
                    "0%, 100%": {
                        opacity: string;
                    };
                    "50%": {
                        opacity: string;
                    };
                };
                shimmer: {
                    "0%": {
                        backgroundPosition: string;
                    };
                    "100%": {
                        backgroundPosition: string;
                    };
                };
            };
            animation: {
                "fade-up": string;
                "pulse-soft": string;
                shimmer: string;
            };
            backgroundImage: {
                noise: string;
                "halo-cyan": string;
                "halo-violet": string;
            };
        };
    };
    plugins: any[];
};
export default _default;
