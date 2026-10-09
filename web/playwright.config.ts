import { defineConfig, devices } from '@playwright/test';

const CONTROL_SECRET = 'e2e-control-secret-0123456789abcdef';
const API = 'http://localhost:8100';
const WEB = 'http://localhost:3200';

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  workers: 1,
  use: { baseURL: WEB, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: 'node e2e/fake-llm.mjs', url: 'http://localhost:4900/health', reuseExistingServer: true },
    {
      // downgrade+upgrade gives every run an empty database (the 3-key limit would otherwise trip)
      command:
        'uv run alembic downgrade base && uv run alembic upgrade head && uv run uvicorn --factory app.main:create_app --port 8100',
      cwd: '../api',
      url: `${API}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: 'postgresql://gateway:gateway@localhost:5434/gateway',
        REDIS_URL: 'redis://localhost:6380/1',
        CEREBRAS_API_KEY: 'fake',
        OPENROUTER_API_KEY: 'fake',
        CEREBRAS_BASE_URL: 'http://localhost:4900/cerebras/v1',
        OPENROUTER_BASE_URL: 'http://localhost:4900/openrouter/v1',
        CONTROL_JWT_SECRET: CONTROL_SECRET,
        METRICS_TOKEN: 'e2e-metrics-token',
        WEB_ORIGIN: WEB,
      },
    },
    {
      command: 'npx next dev -p 3200',
      url: WEB,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        E2E: '1',
        API_URL: API,
        NEXT_PUBLIC_API_URL: API,
        AUTH_SECRET: 'e2e-auth-secret-0123456789abcdef0123456789',
        AUTH_TRUST_HOST: 'true',
        AUTH_GITHUB_ID: 'unused',
        AUTH_GITHUB_SECRET: 'unused',
        CONTROL_JWT_SECRET: CONTROL_SECRET,
      },
    },
  ],
});
