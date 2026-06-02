import { expect, type Locator, type Page } from "@playwright/test";

export function collectPageErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    errors.push(error.message);
  });
  return errors;
}

export async function expectNoPageErrors(errors: string[]) {
  expect(errors.filter((error) => !error.includes("Failed to load resource"))).toEqual([]);
}

export function fieldByIndex(page: Page, index: number): Locator {
  return page.locator(".field-row").nth(index);
}

export function fieldControlByIndex(page: Page, index: number, selector: string): Locator {
  return fieldByIndex(page, index).locator(selector).first();
}

export async function selectCustomValue(root: Locator, value: string) {
  await root.locator(".custom-select__native").first().selectOption(value, { force: true });
}

export async function fillInput(locator: Locator, value: string) {
  await locator.fill(value, { force: true });
  await expect(locator).toHaveValue(value);
}

export async function expectToast(page: Page) {
  await expect(page.locator(".toast").last()).toBeVisible();
}

export async function expectTaskDone(page: Page) {
  await expect(page.locator(".task-progress").last()).toBeVisible();
  await expect(page.locator(".task-progress__fill").last()).toHaveAttribute("style", /100%/);
}

export async function gotoAndExpectPage(page: Page, path: string, pageClass: string) {
  await page.goto(path);
  await expect(page.locator(pageClass)).toBeVisible();
}
