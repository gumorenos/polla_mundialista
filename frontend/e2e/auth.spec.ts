import { test, expect } from '@playwright/test'
import { mockAllApiStubs, mockAuthNone, mockAuthOk, mockSimulationData, setupAuthenticated, setupUnauthenticated } from './helpers/mocks'

test.describe('Autenticación', () => {
  test('acceder a ruta protegida sin auth redirige a login', async ({ page }) => {
    await setupUnauthenticated(page)
    await page.goto('/simulations')
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test('login con contraseña incorrecta muestra error', async ({ page }) => {
    await setupUnauthenticated(page)
    // Use 403 (not 401) to avoid the client-side redirect that clears error state
    await page.route('/api/auth/login', (route) =>
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Contraseña incorrecta' }),
      })
    )

    await page.goto('/login')
    await page.getByPlaceholder('Contraseña').fill('wrong-password')
    await page.getByRole('button', { name: /Entrar/i }).click()

    await expect(page.getByText(/Contraseña incorrecta/i)).toBeVisible({ timeout: 5000 })
  })

  test('login con contraseña correcta redirige al dashboard', async ({ page }) => {
    // Start unauthenticated
    await mockAllApiStubs(page)
    await mockAuthNone(page)

    await page.goto('/login')
    await expect(page).toHaveURL(/\/login/)

    // Before clicking login, set up the post-login state:
    // re-route auth/status to return authenticated
    await page.route('/api/auth/login', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', must_change_password: false }),
      })
    )
    await mockAuthOk(page)
    await mockSimulationData(page)

    await page.getByPlaceholder('Contraseña').fill('correct-password')
    await page.getByRole('button', { name: /Entrar/i }).click()

    await expect(page).toHaveURL('http://localhost:5173/', { timeout: 10000 })
  })

  test('logout redirige a login', async ({ page }) => {
    await setupAuthenticated(page)
    await page.route('/api/auth/logout', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    )

    await page.goto('/')
    // Wait for authenticated layout — nav links confirm we're past the login redirect
    await expect(page.getByRole('link', { name: 'Simulaciones' })).toBeVisible({ timeout: 10000 })

    const logoutBtn = page.getByRole('button', { name: 'Cerrar sesión' })
    await expect(logoutBtn).toBeVisible({ timeout: 5000 })
    await logoutBtn.click()

    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })
})
