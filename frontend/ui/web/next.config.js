await import("./src/env.js");

/** @type {import('next').NextConfig} */

/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */

const nextConfig = {
    images: {
        domains: ["img.clerk.com" ],
    },
    
};

export default nextConfig;
