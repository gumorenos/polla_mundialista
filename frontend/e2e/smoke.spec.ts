import { test, expect } from '@playwright/test'

/**
 * Smoke test — único test que corre en CI (no necesita backend).
 * Solo verifica que el servidor de desarrollo responde correctamente.
 */
test('servidor responde en /', async ({ page }) => {
  const response = await page.goto('/')
  expect(response?.status()).toBeLessThan(400)
  await expect(page).toHaveURL(/.*/)
})
