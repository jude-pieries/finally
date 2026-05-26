import { test, expect } from '@playwright/test';

// ─── Backend API Tests (no browser needed) ────────────────────────────────

test('health check returns ok', async ({ request }) => {
  const res = await request.get('/api/health');
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.status).toBe('ok');
  expect(data.market_data).toBe('simulator');
  expect(typeof data.tickers).toBe('number');
});

test('watchlist returns default 10 tickers', async ({ request }) => {
  const res = await request.get('/api/watchlist');
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.tickers).toHaveLength(10);
  expect(data.tickers).toContain('AAPL');
  expect(data.tickers).toContain('MSFT');
});

test('portfolio has $10k cash on fresh start', async ({ request }) => {
  const res = await request.get('/api/portfolio');
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.cash_balance).toBeCloseTo(10000.0, 0);
  expect(data.positions).toBeInstanceOf(Array);
});

test('add ticker to watchlist', async ({ request }) => {
  // Add PYPL
  const addRes = await request.post('/api/watchlist', {
    data: { ticker: 'PYPL' }
  });
  expect([200, 409]).toContain(addRes.status()); // 200 if new, 409 if already present

  // Verify it's in the watchlist
  const listRes = await request.get('/api/watchlist');
  const data = await listRes.json();
  expect(data.tickers).toContain('PYPL');
});

test('remove ticker from watchlist', async ({ request }) => {
  // First ensure PYPL is present
  await request.post('/api/watchlist', { data: { ticker: 'PYPL' } });

  // Remove it
  const delRes = await request.delete('/api/watchlist/PYPL');
  expect(delRes.status()).toBe(204);

  // Verify it's gone
  const listRes = await request.get('/api/watchlist');
  const data = await listRes.json();
  expect(data.tickers).not.toContain('PYPL');
});

test('buy shares reduces cash and creates position', async ({ request }) => {
  // Get initial state
  const before = await (await request.get('/api/portfolio')).json();
  const initialCash = before.cash_balance;

  // Wait for prices to populate (simulator needs a moment)
  await new Promise(r => setTimeout(r, 2000));

  // Buy 1 share of AAPL
  const tradeRes = await request.post('/api/portfolio/trade', {
    data: { ticker: 'AAPL', quantity: 1, side: 'buy' }
  });
  const tradeData = await tradeRes.json();
  expect(tradeData.success).toBe(true);
  expect(tradeData.cash_balance).toBeLessThan(initialCash);

  // Verify position exists
  const after = await (await request.get('/api/portfolio')).json();
  const aapl = after.positions.find((p: { ticker: string }) => p.ticker === 'AAPL');
  expect(aapl).toBeDefined();
  expect(aapl.quantity).toBeGreaterThan(0);
});

test('sell shares increases cash and removes position', async ({ request }) => {
  // Ensure we have a position (buy 1 share first)
  await new Promise(r => setTimeout(r, 2000));
  await request.post('/api/portfolio/trade', {
    data: { ticker: 'AAPL', quantity: 1, side: 'buy' }
  });

  const before = await (await request.get('/api/portfolio')).json();
  const initialCash = before.cash_balance;
  const aaplBefore = before.positions.find((p: { ticker: string }) => p.ticker === 'AAPL');
  expect(aaplBefore).toBeDefined();

  // Sell all AAPL
  const sellRes = await request.post('/api/portfolio/trade', {
    data: { ticker: 'AAPL', quantity: aaplBefore.quantity, side: 'sell' }
  });
  const sellData = await sellRes.json();
  expect(sellData.success).toBe(true);
  expect(sellData.cash_balance).toBeGreaterThan(initialCash);

  // Position should be gone
  const after = await (await request.get('/api/portfolio')).json();
  const aaplAfter = after.positions.find((p: { ticker: string }) => p.ticker === 'AAPL');
  expect(aaplAfter).toBeUndefined();
});

test('chat endpoint responds with mock LLM', async ({ request }) => {
  const res = await request.post('/api/chat', {
    data: { message: 'How is my portfolio looking?' }
  });
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(typeof data.message).toBe('string');
  expect(data.message.length).toBeGreaterThan(0);
  expect(data.trades).toBeInstanceOf(Array);
  expect(data.watchlist_changes).toBeInstanceOf(Array);
  expect(data.errors).toBeInstanceOf(Array);
});

test('ticker price history returns data after warmup', async ({ request }) => {
  // Wait for simulator to populate history
  await new Promise(r => setTimeout(r, 3000));

  const res = await request.get('/api/prices/AAPL/history');
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.ticker).toBe('AAPL');
  expect(data.history).toBeInstanceOf(Array);
  // After 3s of simulator running at 500ms intervals, should have some history
  expect(data.history.length).toBeGreaterThan(0);
});

test('portfolio history has snapshots', async ({ request }) => {
  // The lifespan starts a 30s snapshot loop. Snapshots also happen on trade.
  // Run a trade to trigger an immediate snapshot.
  await new Promise(r => setTimeout(r, 2000));
  await request.post('/api/portfolio/trade', {
    data: { ticker: 'AAPL', quantity: 1, side: 'buy' }
  });

  const res = await request.get('/api/portfolio/history');
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(data.history).toBeInstanceOf(Array);
  expect(data.history.length).toBeGreaterThan(0);
});

// ─── Frontend UI Tests ───────────────────────────────────────────────────────

test('home page loads with trading terminal', async ({ page }) => {
  await page.goto('/');
  // Should not be a 404 or error page
  await expect(page).not.toHaveTitle(/404|Error/i);
  // Check for some key UI elements
  await page.waitForLoadState('networkidle');
  // The page should have content (not blank)
  const bodyText = await page.textContent('body');
  expect(bodyText).toBeTruthy();
  expect(bodyText!.length).toBeGreaterThan(100);
});

test('watchlist tickers visible on page', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  // Wait up to 5s for prices to appear
  await page.waitForTimeout(3000);
  // AAPL should be visible somewhere on the page
  const pageContent = await page.textContent('body');
  expect(pageContent).toContain('AAPL');
});

test('prices update in the watchlist', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  // Wait for SSE to deliver prices
  await page.waitForTimeout(3000);
  // A dollar sign should appear (prices shown as currency)
  const pageContent = await page.textContent('body');
  expect(pageContent).toMatch(/\$\d+/);
});
