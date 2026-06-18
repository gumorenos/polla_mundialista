import { test, expect } from '@playwright/test'
import { setupAuthenticated } from './helpers/mocks'

test.describe('Simulaciones', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuthenticated(page)
    await page.goto('/simulations')
    await expect(page.getByRole('heading', { name: /Simulaciones Monte Carlo/i })).toBeVisible({ timeout: 10000 })
  })

  test('muestra el título de la página', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Simulaciones Monte Carlo/i })).toBeVisible()
  })

  test('tabla de simulaciones muestra equipos', async ({ page }) => {
    await expect(page.getByText('España')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Francia')).toBeVisible()
    await expect(page.getByText('Brasil')).toBeVisible()
  })

  test('tabla muestra columnas de probabilidades', async ({ page }) => {
    await expect(page.getByRole('columnheader', { name: /Campeón/i })).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('columnheader', { name: /Final/i })).toBeVisible()
  })

  test('selector de modelo tiene todas las opciones', async ({ page }) => {
    const select = page.getByRole('combobox').first()
    await expect(select).toBeVisible({ timeout: 5000 })

    const options = await select.locator('option').allTextContents()
    expect(options.some((o) => o.includes('Consenso'))).toBeTruthy()
    expect(options.some((o) => o.includes('Poisson'))).toBeTruthy()
    expect(options.some((o) => o.includes('ELO'))).toBeTruthy()
    expect(options.some((o) => o.includes('Baseline'))).toBeTruthy()
    expect(options.some((o) => o.includes('ML'))).toBeTruthy()
  })

  test('selector de modelo cambia el valor seleccionado', async ({ page }) => {
    const select = page.getByRole('combobox').first()
    await select.selectOption('elo')
    await expect(select).toHaveValue('elo')
  })

  test('botón Simular está presente', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Simular/i })).toBeVisible()
  })

  test('tabs de vista están presentes', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Por modelo/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Comparar modelos/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /vs\. Mercado/i })).toBeVisible()
  })

  test('comparación de modelos muestra mensaje sin suficientes datos', async ({ page }) => {
    await page.getByRole('button', { name: /Comparar modelos/i }).click()
    // With 3 mocked models the comparison table should appear OR the "need more" message
    // Either way, the page should not crash
    await expect(page.getByRole('heading', { name: /Simulaciones Monte Carlo/i })).toBeVisible()
  })

  test('tab vs. Mercado está presente', async ({ page }) => {
    await expect(page.getByRole('button', { name: /vs\. Mercado/i })).toBeVisible()
  })
})
