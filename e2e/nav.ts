import { expect, type Locator, type Page } from '@playwright/test';

/* The main navigation is grouped into menus (11-03 F4, C1): most links sit in a closed panel until their group is opened,
   and on phones everything sits behind the Menu button. These helpers find and follow a link wherever it sits. */

export const mainNav = (page: Page) => page.getByRole('navigation', { name: 'Main' });

/** A main navigation link, whether or not its menu is open. */
export const navLink = (page: Page, name: string | RegExp): Locator =>
  mainNav(page).getByRole('link', { name, exact: typeof name === 'string', includeHidden: true });

/** Opens the phone menu and the link's group if they are closed, then follows the link. */
export async function openNav(page: Page, name: string | RegExp) {
  const menu = page.getByRole('button', { name: 'Menu' });
  if (await menu.isVisible() && (await menu.getAttribute('aria-expanded')) !== 'true') await menu.click();
  const link = navLink(page, name);
  await expect(link).toHaveCount(1);
  if (!(await link.isVisible())) {
    const inner = page.getByRole('link', { name, exact: typeof name === 'string', includeHidden: true });  // `has` is relative to the group
    await mainNav(page).locator('.nav-group', { has: inner }).locator(':scope > button').click();
  }
  await link.click();
}

/** Asserts which entries this person's navigation offers (open or closed menus alike). */
export async function expectNav(page: Page, shown: string[], hidden: string[]) {
  for (const name of shown) await expect(navLink(page, name), `nav shows ${name}`).toHaveCount(1);
  for (const name of hidden) await expect(navLink(page, name), `nav hides ${name}`).toHaveCount(0);
}
