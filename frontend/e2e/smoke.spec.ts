import { test, expect } from '@playwright/test'

// Critical-path smoke tests against fixture data. These assume the stack is up
// with the synthetic league loaded and analytics computed (make demo-data).

test('home shows the champions and leaderboard', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('h1')).toBeVisible()
  // The all-time leaderboard table renders 10 managers.
  const rows = page.locator('.data-table').last().locator('tbody tr')
  await expect(rows).toHaveCount(10)
})

test('manager profile renders career charts', async ({ page }) => {
  await page.goto('/managers/1')
  await expect(page.locator('canvas').first()).toBeVisible()
  await expect(page.locator('h1')).toBeVisible()
})

test('rivalries heatmap renders', async ({ page }) => {
  await page.goto('/rivalries')
  await expect(page.locator('canvas').first()).toBeVisible()
})

test('hall of fame shows award cards', async ({ page }) => {
  await page.goto('/hall-of-fame')
  await expect(page.locator('.award-card').first()).toBeVisible()
})

test('rivalry pair page shows the head-to-head record', async ({ page }) => {
  await page.goto('/rivalries/8/2')
  await expect(page.locator('.stat-tile').first()).toBeVisible()
  await expect(page.locator('h1')).toContainText('vs')
})

test('season share card renders and downloads a PNG', async ({ page }) => {
  await page.goto('/managers/8/card')
  await expect(page.locator('.card-preview svg')).toBeVisible()
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.click('button.btn'),
  ])
  expect(download.suggestedFilename()).toMatch(/\.png$/)
})
