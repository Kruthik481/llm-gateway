import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Tailwind v4 runs as a Turbopack loader; without this rule @theme and utilities never compile.
  turbopack: {
    rules: {
      '*.css': { loaders: ['@tailwindcss/turbopack'], as: '*.css' },
    },
  },
};

export default nextConfig;
