import { test, expect } from '@playwright/test';

test.beforeEach(async ({ request }) => {
  const people = await (await request.get('/api/personas')).json();
  for (const person of people) {
    const result = await (await request.get(`/api/items?persona_id=${person.id}&page_size=200`)).json();
    for (const item of result.items) await request.delete(`/api/items/${item.id}`);
  }
  for (const person of people.slice(1)) await request.delete(`/api/personas/${person.id}`);
});

test('wardrobe saves, edits, searches and deletes real items', async ({ page }) => {
  await page.goto('/wardrobe');
  await page.getByText('Add a piece by hand', { exact: false }).click();
  await page.getByLabel('Name', { exact: true }).fill('E2E linen shirt');
  await page.getByLabel('Color', { exact: true }).fill('Navy');
  const documentId = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole('button', { name: 'Save piece' }).click();
  await expect(page.getByRole('heading', { name: 'E2E linen shirt' })).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentId);
  await page.getByRole('button', { name: 'Edit E2E linen shirt' }).click();
  await expect(page.getByText('Edit your piece', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('E2E linen shirt');
  await page.getByLabel('Name', { exact: true }).fill('E2E edited shirt');
  await page.getByLabel('Name', { exact: true }).press('Enter');
  await expect(page.getByRole('heading', { name: 'E2E edited shirt' })).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentId);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'E2E edited shirt' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search wardrobe' }).fill('absent');
  await expect(page.getByRole('heading', { name: 'E2E edited shirt' })).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Search wardrobe' }).fill('edited');
  await page.getByRole('button', { name: 'Delete E2E edited shirt' }).click();
  await page.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByRole('heading', { name: 'E2E edited shirt' })).toHaveCount(0);
});

test('settings and people persist and empty wardrobe reports useful gaps', async ({ page }) => {
  await page.goto('/settings');
  await page.getByLabel('Your city').fill('Toronto');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await expect(page.getByRole('status')).toContainText('saved');
  await page.reload(); await expect(page.getByLabel('Your city')).toHaveValue('Toronto');
  await page.getByLabel('New person name').fill('E2E partner');
  await page.getByRole('button', { name: 'Add a person' }).click();
  await expect(page.getByLabel('Name for E2E partner')).toBeVisible();
  await page.goto('/');
  await page.getByLabel('How are you feeling?').fill('Relaxed');
  await page.getByText('Set the temperature yourself').click();
  await page.getByLabel('Temperature in °C').fill('18');
  await page.getByLabel('A little choice').selectOption('1');
  const documentId = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole('button', { name: 'Find my outfit' }).click();
  await expect(page.getByRole('heading', { name: 'No complete outfit possible' })).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentId);
  await expect(page.getByText('No primary top fits', { exact: false }).first()).toBeVisible();
});


test('photo queue reviews drafts, keeps failed files visible, saves all and supports quick add', async ({ page, request }) => {
  await page.goto('/wardrobe');
  const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5wAAAABJRU5ErkJggg==', 'base64');
  await page.locator('#photo-upload').setInputFiles([
    { name: 'outfit.png', mimeType: 'image/png', buffer: pixel },
    { name: 'not-a-photo.txt', mimeType: 'text/plain', buffer: Buffer.from('not a photo') },
  ]);
  await expect(page.getByText('2 photos processed')).toBeVisible();
  await expect(page.locator('.queue-list')).toContainText('Failed');
  await page.getByRole('button', { name: 'Review', exact: true }).first().click();
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Vision shirt');
  await page.getByLabel('Name', { exact: true }).fill('Reviewed shirt');
  await page.getByRole('button', { name: 'Save piece' }).click();
  await expect(page.getByRole('heading', { name: 'Reviewed shirt' })).toBeVisible();
  await page.getByRole('button', { name: 'Save all', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Vision jeans' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save all', exact: true })).toBeDisabled();
  await page.getByLabel('Save without review').check();
  await page.locator('#photo-upload').setInputFiles([{name:'quick.png',mimeType:'image/png',buffer:pixel}]);
  await expect(page.getByRole('status')).toContainText('2 piece(s) saved from quick.png');
  const collection = await (await request.get('/api/items')).json();
  expect(collection.total).toBe(4);
  expect(collection.items.every((item: {has_photo: boolean}) => item.has_photo)).toBe(true);
});


test('long mobile searches cannot break the interactive wardrobe', async ({ page }) => {
  await page.setViewportSize({width:375,height:812});
  await page.goto('/wardrobe');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const search=page.getByRole('searchbox',{name:'Search wardrobe'});
  await search.fill('x'.repeat(101));
  await expect(search).toHaveValue('x'.repeat(100));
  await search.fill('');
  await expect(page.getByText('Your wardrobe is empty.',{exact:false})).toBeVisible();
});

test('a delayed photo replacement stays attached to the original item when the editor changes', async ({ page, request }) => {
  const first=await (await request.post('/api/items',{data:{name:'First shirt',category:'shirt',warmth:2,formality:2}})).json();
  const second=await (await request.post('/api/items',{data:{name:'Second shirt',category:'shirt',warmth:2,formality:2}})).json();
  await page.addInitScript(() => {
    const original=Blob.prototype.arrayBuffer;
    Blob.prototype.arrayBuffer=function() {
      (window as any).__photoTransferWaiting=true;
      return new Promise<ArrayBuffer>((resolve,reject)=> {
        (window as any).__releasePhotoTransfer=()=>original.call(this).then(resolve,reject);
      });
    };
  });
  await page.goto('/wardrobe');
  await page.getByRole('button',{name:'Edit First shirt'}).click();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('First shirt');
  await page.locator('#replace-photo').setInputFiles({name:'replacement.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5wAAAABJRU5ErkJggg==','base64')});
  await page.waitForFunction(()=>(window as any).__photoTransferWaiting===true);
  await page.getByRole('button',{name:'Edit Second shirt'}).click();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('Second shirt');
  await page.evaluate(()=>(window as any).__releasePhotoTransfer());
  await expect(page.getByRole('status')).toContainText('Photo replaced');
  const firstAfter=await (await request.get(`/api/items/${first.id}`)).json();
  const secondAfter=await (await request.get(`/api/items/${second.id}`)).json();
  expect(firstAfter.has_photo).toBe(true); expect(secondAfter.has_photo).toBe(false);
});
