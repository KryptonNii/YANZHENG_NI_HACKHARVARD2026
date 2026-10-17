// Records actual TrialPilot UI against the isolated real API. No response mocking.
// Run from repository root. Requires existing Edge + web's locked Playwright.
// TP_CAPTURE_DIR and TP_VIDEO_DIR must name independent output directories.
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(path.resolve('web/package.json'));
const { chromium, expect: baseExpect } = require('@playwright/test');
const expect = baseExpect.configure({ timeout: 40000 });
const captureDir = process.env.TP_CAPTURE_DIR;
const videoDir = process.env.TP_VIDEO_DIR;
if (!captureDir) throw new Error('Set TP_CAPTURE_DIR');
await mkdir(captureDir, { recursive: true });
if (videoDir) await mkdir(videoDir, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({
  baseURL: process.env.TP_WEB_URL || 'http://127.0.0.1:5181',
  viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1,
  ...(videoDir ? { recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } } } : {}),
});
await context.addInitScript(() => localStorage.setItem('tp.identity', 'alex.author'));
const page = await context.newPage();
page.setDefaultTimeout(40000);
const log = [];
let origin;
async function stage(second, name, action) {
  if (origin && videoDir) await new Promise(r => setTimeout(r, Math.max(0, origin + second * 1000 - Date.now())));
  const elapsed = origin ? (Date.now() - origin) / 1000 : 0;
  console.log(`${elapsed.toFixed(2)}s ${name}`);
  await action();
  log.push({ second, actual_second: elapsed, name, url: page.url() });
}
async function shot(name, locator) {
  if (locator) await locator.scrollIntoViewIfNeeded();
  for (const close of await page.getByRole('button', { name: 'Dismiss notification', exact: true }).all()) await close.click();
  await page.screenshot({ path: path.join(captureDir, `${name}.png`) });
}
let interventionId;
try {
  await page.goto('/');
  await expect(page.getByTestId('demo-chips')).toBeVisible();
  origin = Date.now();
  await stage(0, 'Import home', () => shot('01-home'));
  await stage(8, 'Import BOREAS', async () => {
    await page.getByTestId('demo-chips').getByRole('button', { name: /NCT03930732/ }).click();
    await expect(page.getByTestId('trial-card')).toBeVisible();
    await shot('02-import');
  });
  await stage(18, 'Review cached protocol transcription', async () => {
    await page.getByTestId('extract-registry').click();
    await expect(page.getByTestId('protocol-review')).toBeVisible();
    await page.getByTestId('protocol-review').evaluate(el => window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 110));
    await shot('03-protocol-review');
  });
  await stage(31, 'Accept candidates and apply protocol', async () => {
    await page.getByTestId('protocol-review').getByRole('button', { name: 'Accept all remaining' }).click();
    await page.getByTestId('apply-extraction').click();
    await expect(page.getByTestId('protocol-review')).toBeHidden();
    await shot('04-protocol-applied', page.getByTestId('trial-card'));
  });
  await stage(40, 'Open simulator on saved design version', async () => {
    await page.getByTestId('open-simulator').click();
    await expect(page.getByTestId('save-scenario')).toBeEnabled();
    await page.getByTestId('levers-panel').evaluate(el => { el.parentElement.scrollTop = 0; });
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('05-simulator-baseline');
  });
  await stage(50, 'Change monitoring and supply inputs', async () => {
    await page.getByTestId('lever-remote-monitoring').fill('50');
    await page.getByRole('radio', { name: 'On-demand resupply' }).click();
    await expect(page.getByTestId('save-scenario')).toBeEnabled();
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('06-simulator-scenario');
  });
  await stage(62, 'Inspect forecast and supply draw counts', async () => {
    await shot('07-forecast', page.getByTestId('forecast-chart'));
  });
  await stage(72, 'Inspect carbon provenance', async () => {
    await page.getByTestId('metric-co2e_kg-value').click();
    await expect(page.getByTestId('provenance-param').first()).toBeVisible();
    await shot('08-provenance');
  });
  await stage(84, 'Save version-bound scenario', async () => {
    await page.keyboard.press('Escape');
    await page.getByTestId('save-scenario').click();
    await page.getByTestId('save-name').fill('Demo — remote monitoring + on-demand supply');
    await page.getByTestId('save-confirm').click();
    await expect(page.getByTestId('submit-approval')).toBeVisible();
  });
  await stage(94, 'Submit and block self-approval', async () => {
    await page.getByTestId('submit-approval').click();
    await page.getByTestId('sign-pin').fill('1111');
    await page.getByTestId('sign-button').click();
    await expect(page.getByTestId('sign-error')).toContainText("Authors can't approve their own work.");
    await shot('09-self-approval-blocked');
  });
  await stage(103, 'Reviewer demonstration signature', async () => {
    await page.getByTestId('identity-switcher').selectOption('riley.reviewer');
    await page.getByTestId('sign-pin').fill('2222');
    await page.getByTestId('sign-button').click();
    await expect(page.getByTestId('signature-list')).toContainText(/reviewed by Riley/i);
  });
  await stage(111, 'QA demonstration signature', async () => {
    await page.getByTestId('identity-switcher').selectOption('sam.qa');
    await page.getByTestId('sign-pin').fill('3333');
    await page.getByTestId('sign-button').click();
    await expect(page.getByTestId('approval-status')).toContainText('Approved');
    await shot('10-demo-approved');
  });
  await stage(121, 'Verify current audit chain', async () => {
    await page.goto('/audit');
    await page.getByRole('button', { name: 'Verify chain', exact: true }).click();
    await expect(page.getByTestId('chain-result')).toContainText(/intact/i);
    await shot('11-audit');
  });
  await stage(131, 'Start synthetic operations feed', async () => {
    await page.goto('/command/demo-40');
    await page.getByTestId('identity-switcher').selectOption('alex.author');
    await page.getByTestId('start-simulation').click();
    await expect(page.getByTestId('advance-1-week')).toBeEnabled();
    await shot('12-command');
  });
  await stage(140, 'Acknowledge overstock and plan intervention', async () => {
    const alert = page.getByTestId('alert-drug_overstock').first();
    await alert.getByRole('button', { name: 'Acknowledge', exact: true }).click();
    await alert.getByRole('button', { name: 'Plan intervention', exact: true }).click();
    const response = page.waitForResponse(r => r.url().endsWith('/interventions') && r.request().method() === 'POST');
    await page.getByRole('dialog').getByRole('button', { name: 'Save intervention', exact: true }).click();
    interventionId = (await (await response).json()).id;
    const intervention = page.getByTestId(`intervention-${interventionId}`);
    await intervention.getByRole('button', { name: 'Start intervention', exact: true }).click();
    await expect(intervention).toContainText('in progress');
    await shot('13-intervention', intervention);
  });
  await stage(151, 'Advance six simulated weeks and inspect effect', async () => {
    await page.getByRole('button', { name: 'Advance 6 weeks', exact: true }).click();
    await expect(page.getByTestId('advance-1-week')).toBeEnabled();
    const intervention = page.getByTestId(`intervention-${interventionId}`);
    await expect(intervention.getByTestId('effect-verdict')).toBeVisible();
    await shot('14-effect', intervention);
  });
  await stage(162, 'Inspect published-method comparisons', async () => {
    await page.goto('/science');
    await expect(page.getByTestId('science-band-unit')).toBeVisible();
    await shot('15-science');
  });
  await stage(171, 'Inspect exact validation execution and download evidence', async () => {
    await page.goto('/validation');
    await expect(page.getByTestId('execution-summary')).toContainText('Tested commit:');
    await expect(page.getByTestId('evidence-attachments')).not.toContainText('(0)');
    await shot('16-validation');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Download evidence manifest', exact: true }).click();
    const download = await downloadPromise;
    await download.saveAs(path.join(captureDir, 'downloaded-evidence-manifest.json'));
  });
  await stage(182, 'End capture', async () => {});
  await writeFile(path.join(captureDir, 'capture-log.json'), JSON.stringify({ started_at: new Date(origin).toISOString(), duration_seconds: (Date.now()-origin)/1000, automated_demo: true, voiceover: false, events: log }, null, 2));
} catch (error) {
  await shot('capture-error');
  throw error;
} finally {
  const video = page.video();
  await context.close();
  if (video) console.log(`VIDEO ${await video.path()}`);
  await browser.close();
}
