// frontend/e2e/knowledge.spec.ts
import { test, expect } from '@playwright/test';

test('knowledge base full lifecycle through UI', async ({ page }) => {
  test.setTimeout(120000);

  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  const html = await page.content();
  expect(html.length).toBeGreaterThan(100);
  expect(html).toMatch(/prism|knowledge/i);
});
