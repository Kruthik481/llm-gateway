import { expect, test } from '@playwright/test';

test('sign in, create a key, stream in the playground, then see it in usage', async ({ page }) => {
  await page.goto('/api/auth/signin');
  await page.getByLabel('Login').fill('e2e-user');
  await page.getByRole('button', { name: 'Sign in with E2E' }).click();

  await page.goto('/keys');
  await page.getByLabel('Key name').fill('laptop');
  await page.getByRole('button', { name: 'Create key' }).click();
  await expect(page.getByTestId('new-key')).toContainText('lgw_');
  await expect(page.getByRole('table', { name: 'API keys' })).toContainText('laptop');

  await page.getByRole('link', { name: 'Try it in the playground' }).click();
  await expect(page.getByPlaceholder('lgw_…')).toHaveValue(/^lgw_/);
  await page.getByLabel('Prompt').fill('Say hello');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByTestId('output')).toHaveText('Hello from the fake model.');
  await expect(page.getByTestId('meta')).toContainText('cerebras');

  await page.getByLabel('Simulate Cerebras outage').check();
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByTestId('meta')).toContainText('openrouter');

  await page.goto('/usage');
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('table', { name: 'Recent requests' })).toContainText('fallback');
  }).toPass({ timeout: 15_000 });
});
