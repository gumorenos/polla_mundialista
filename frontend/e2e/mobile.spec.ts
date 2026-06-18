import { test, expect } from '@playwright/test'
import { setupAuthenticated } from './helpers/mocks'

// These tests run using the 'mobile' project (iPhone 12 viewport) from playwright.config.ts

test.describe('Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuthenticated(page)
    await page.goto('/')
    // On mobile, wait for the mobile top bar (not the desktop nav)
    await expect(page.getByRole('button', { name: 'Abrir menú' })).toBeVisible({ timeout: 10000 })
  })

  test('menú hamburguesa está visible en móvil', async ({ page }) => {
    const hamburger = page.getByRole('button', { name: 'Abrir menú' })
    await expect(hamburger).toBeVisible()
  })

  test('menú hamburguesa abre el sidebar en móvil', async ({ page }) => {
    await page.getByRole('button', { name: 'Abrir menú' }).click()

    // After opening, nav links should be visible inside the sidebar
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({ timeout: 3000 })
    await expect(page.getByRole('link', { name: 'Simulaciones' })).toBeVisible()
  })

  test('menú hamburguesa cierra al pulsar el botón de cerrar', async ({ page }) => {
    await page.getByRole('button', { name: 'Abrir menú' }).click()
    // Close button appears inside the open sidebar
    const closeBtn = page.getByRole('button', { name: 'Cerrar menú' })
    await expect(closeBtn).toBeVisible({ timeout: 3000 })
    await closeBtn.click()
    // Sidebar slides off-screen via CSS transform — check geometric position, not CSS visibility
    await expect(closeBtn).not.toBeInViewport({ timeout: 3000 })
  })

  test('menú hamburguesa cierra al tocar el overlay', async ({ page }) => {
    await page.getByRole('button', { name: 'Abrir menú' }).click()
    const closeBtn = page.getByRole('button', { name: 'Cerrar menú' })
    await expect(closeBtn).toBeVisible({ timeout: 3000 })

    // Tap on the overlay area (right side, outside the sidebar)
    const vp = page.viewportSize()!
    await page.mouse.click(vp.width - 20, vp.height / 2)

    // Sidebar slides off-screen via CSS transform — check geometric position, not CSS visibility
    await expect(closeBtn).not.toBeInViewport({ timeout: 3000 })
  })

  test('tablas tienen overflow scroll horizontal en móvil', async ({ page }) => {
    await setupAuthenticated(page)
    await page.goto('/simulations')
    await expect(page.getByRole('heading', { name: /Simulaciones Monte Carlo/i })).toBeVisible({ timeout: 10000 })

    const tableWrapper = page.locator('.overflow-x-auto').first()
    await expect(tableWrapper).toBeVisible()

    const overflow = await tableWrapper.evaluate((el) =>
      window.getComputedStyle(el).overflowX
    )
    expect(['auto', 'scroll']).toContain(overflow)
  })

  test('página de simulaciones es accesible desde nav en móvil', async ({ page }) => {
    // Open mobile menu and navigate to Simulations
    await page.getByRole('button', { name: 'Abrir menú' }).click()
    await page.getByRole('link', { name: 'Simulaciones' }).click()

    await expect(page).toHaveURL(/\/simulations/, { timeout: 5000 })
    await expect(page.getByRole('heading', { name: /Simulaciones Monte Carlo/i })).toBeVisible({ timeout: 8000 })
  })
})
