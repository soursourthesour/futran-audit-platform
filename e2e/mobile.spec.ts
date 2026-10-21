import { readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

// Meridian's open attestation campaign and a named-user confirmation link (start-server.sh … late)
const late = () => JSON.parse(readFileSync(`${__dirname}/../backend/data/e2e-late.json`, 'utf8')) as { attest_link: string; confirm_link: string };

test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });

/** No sideways scrolling, and every control is at least 44 px tall (spec §13 accessibility). */
async function checkLayout(page: Page, where: string) {
  const r = await page.evaluate(() => {
    const wide = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const small: string[] = [];
    document.querySelectorAll<HTMLElement>('button, a.btn, select, textarea, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), label.check').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.height < 44) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(b.height)}px`);
    });
    return { wide, small };
  });
  expect(r.wide, `${where}: page scrolls sideways`).toBeLessThanOrEqual(0);
  expect(r.small, `${where}: controls under 44 px`).toEqual([]);
}

test('attestation on a phone', async ({ page }) => {
  await page.goto(late().attest_link);
  await expect(page.getByLabel('Your name', { exact: true })).toBeVisible();
  await checkLayout(page, 'attestation start');
  await page.getByLabel('Your name', { exact: true }).fill('Mira Iyer');
  await page.getByLabel('Department', { exact: true }).selectOption({ label: 'Engineering' });
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('ChatGPT').check();
  await page.getByLabel('Personal, free').check();
  await checkLayout(page, 'attestation tools');
  await page.screenshot({ path: 'screenshots/p7-phone-attestation.png', fullPage: true });
  await page.getByRole('button', { name: 'Next: what you use it for' }).click();
  await page.getByLabel('Writing and editing').check();
  await page.getByLabel('Client or customer data').check();
  await checkLayout(page, 'attestation purposes');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByLabel('I have read the AI use policy', { exact: true }).check();
  await checkLayout(page, 'attestation policy');
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByRole('heading', { name: 'Thank you' })).toBeVisible();
});

test('named-user confirmation on a phone', async ({ page }) => {
  await page.goto(late().confirm_link);
  await expect(page.getByRole('heading').first()).toBeVisible();
  await expect(page.getByText('Code completion').first()).toBeVisible();
  await checkLayout(page, 'confirmation');
  await page.screenshot({ path: 'screenshots/p7-phone-confirmation.png', fullPage: true });
});
