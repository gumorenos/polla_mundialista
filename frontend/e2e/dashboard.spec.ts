import { test, expect } from '@playwright/test'
import { setupAuthenticated } from './helpers/mocks'

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuthenticated(page)
    await page.goto('/')
    // Wait until the Layout nav is visible (auth resolved + not on login page)
    await expect(page.getByRole('navigation')).toBeVisible({ timeout: 10000 })
  })

  test('dashboard carga con el título de la app', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Oráculo Mundial 2026/i }).first()).toBeVisible()
  })

  test('sidebar muestra todos los links de navegación', async ({ page }) => {
    await expect(page.getByRole('link', { name: 'Simulaciones' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Modelos' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Jobs' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Noticias' })).toBeVisible()
  })

  test('botón Full Refresh está visible y es clickeable', async ({ page }) => {
    const btn = page.getByRole('button', { name: /Full Refresh/i })
    await expect(btn).toBeVisible({ timeout: 8000 })
    await expect(btn).toBeEnabled()
  })

  test('theme switcher cambia el tema a Dark', async ({ page }) => {
    await page.getByTitle('Tema oscuro').click()
    await expect(page.locator('html')).toHaveClass(/theme-dark/, { timeout: 3000 })
  })

  test('theme switcher cambia el tema a Light', async ({ page }) => {
    await page.getByTitle('Tema oscuro').click()
    await page.getByTitle('Tema claro').click()
    await expect(page.locator('html')).toHaveClass(/theme-light/, { timeout: 3000 })
  })

  test('theme switcher cambia el tema a Black', async ({ page }) => {
    await page.getByTitle('AMOLED negro').click()
    await expect(page.locator('html')).toHaveClass(/theme-black/, { timeout: 3000 })
  })

  test('clic en link Simulaciones navega a la página', async ({ page }) => {
    await page.getByRole('link', { name: 'Simulaciones' }).click()
    await expect(page).toHaveURL(/\/simulations/, { timeout: 5000 })
  })
})
