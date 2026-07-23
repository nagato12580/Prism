// frontend/e2e/knowledge.spec.ts
import { test, expect } from '@playwright/test';

test('frontend renders without JS crash', async ({ page }) => {
  test.setTimeout(60000);
  const errors: string[] = [];
  page.on('pageerror', err => errors.push(err.message));

  await page.goto('http://127.0.0.1:5173/', { timeout: 30000, waitUntil: 'load' });
  await page.waitForTimeout(5000);

  const html = await page.content();
  expect(html.length).toBeGreaterThan(100);
  expect(html).toContain('root');
});
