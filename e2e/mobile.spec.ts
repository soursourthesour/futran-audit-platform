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
  await page.getByLabel('ChatGPT', { exact: true }).check();
  await page.getByLabel('Personal, free').check();
  await page.getByLabel('Another AI agent', { exact: true }).check();
  await page.getByRole('textbox', { name: 'Name of the agent' }).fill('Invoice chaser');
  await page.locator('input[name="acct-other_agent"]').first().check();
  await expect(page.getByRole('heading', { name: 'AI agents (tools that take actions for you)' })).toBeVisible();
  await checkLayout(page, 'attestation tools and agents');
  await page.screenshot({ path: 'screenshots/p7-phone-attestation.png', fullPage: true });
  await page.getByRole('button', { name: 'Next: what you use it for' }).click();
  await page.getByLabel('Writing and editing').check();
  await page.getByLabel('Something else', { exact: true }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('Say what else you use AI for.').first()).toBeVisible();
  await page.getByRole('textbox', { name: 'What else?' }).fill('Translating supplier contracts');
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

test('in-app attestation on a phone', async ({ page }) => {
  const signIn = async (email: string) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill('Demo-Password-2026');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).not.toHaveURL(/login/);
    for (let i = 0; i < 3; i++) {
      const p = new URL(page.url()).pathname;
      if (p.startsWith('/welcome/terms')) { await page.getByRole('checkbox', { name: /I accept the terms/ }).check(); await page.getByRole('button', { name: 'Accept and continue' }).click(); }
      else if (p.startsWith('/welcome/notice')) { await page.getByRole('checkbox', { name: 'I have read and understand this notice.' }).check(); await page.getByRole('button', { name: 'Acknowledge and continue' }).click(); }
      else break;
      await page.waitForURL((u) => !u.pathname.startsWith(p));
    }
  };
  await signIn('katrin.vogel@meridian.example');
  await page.goto('/attestation');
  await page.getByRole('button', { name: 'Send attestation' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Send attestation' }).click();
  await expect(page.getByText(/Attestation sent to|already has the attestation/)).toBeVisible();
  await signIn('aarav.menon@meridian.example');
  await page.goto('/my-attestation');
  await expect(page.getByText('To do', { exact: true })).toBeVisible();
  await checkLayout(page, 'my attestation');
  await page.getByRole('button', { name: 'Complete attestation' }).click();
  await expect(page.getByText('aarav.menon@meridian.example')).toBeVisible();
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('GitHub Copilot coding agent', { exact: true }).check();
  await page.getByLabel('Company account').check();
  await checkLayout(page, 'in-app tools and agents');
  await page.getByRole('button', { name: 'Next: what you use it for' }).click();
  await page.getByLabel('Writing or reviewing code').check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByLabel('I have read the AI use policy', { exact: true }).check();
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByText('Thank you. Your attestation has been recorded.')).toBeVisible();
  await expect(page.getByText(/Submitted on/)).toBeVisible();
});
