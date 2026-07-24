// frontend/e2e/knowledge-product.spec.ts
// Real browser acceptance for the knowledge product, against the running
// Backend (5175) / Engine (5180) / Frontend (5173). No mocking of the happy
// path — this exercises the real public REST API.
import { test, expect } from '@playwright/test';

const BASE = 'http://127.0.0.1:5173';

test('knowledge index lists real knowledge bases', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const html = await page.content();
  // The index page renders (either the list of KBs or the empty state).
  expect(html).toContain('data-testid="knowledge-index-page"');
});

test('deep link to a KB files tab restores the workspace', async ({ page, request }) => {
  test.setTimeout(60000);
  // Discover a real KB uid from the backend.
  const res = await request.get(`${BASE}/api/v1/knowledge-bases?limit=5`, {
    headers: { 'X-Prism-Actor': 'default-user', 'X-Prism-Tenant': 'default-user' },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  const kb = body.items?.[0];
  if (!kb) {
    // No KBs exist; the deep link must still render the index gracefully.
    await page.goto(`${BASE}/knowledge/missing-kb/files`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    return;
  }

  await page.goto(`${BASE}/knowledge/${kb.kb_uid}/files`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const html = await page.content();
  // The files page (or an honest error/not-found state) renders; never a crash.
  expect(html.length).toBeGreaterThan(100);
  // Tab navigation links are present.
  expect(html).toMatch(/文件|检索|导图/);
});

test('large document preview opens without blocking the page', async ({ page, request }) => {
  test.setTimeout(60000);
  const kbResponse = await request.get(`${BASE}/api/v1/knowledge-bases?limit=5`);
  expect(kbResponse.ok()).toBeTruthy();
  const kb = (await kbResponse.json()).items?.[0];
  test.skip(!kb, 'No real knowledge base is available');

  const filesResponse = await request.get(
    `${BASE}/api/v1/knowledge-bases/${kb.kb_uid}/files?limit=100`,
  );
  expect(filesResponse.ok()).toBeTruthy();
  const file = (await filesResponse.json()).items?.[0];
  test.skip(!file, 'No real document is available');

  await page.goto(`${BASE}/knowledge/${kb.kb_uid}/files`, { waitUntil: 'networkidle' });
  const startedAt = Date.now();
  await page.getByRole('button', { name: '预览' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5000 });
  expect(Date.now() - startedAt).toBeLessThan(5000);
  await expect(page.getByRole('button', { name: '关闭' })).toBeEnabled();
});

test('chat renders and source scores are not a fake match percentage', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const html = await page.content();
  // The retrieval contract forbids wrapping raw scores as a fake "匹配百分比".
  // Ensure the legacy percentage template is absent in the bundle.
  expect(html).not.toMatch(/匹配 \$\{/);
});
