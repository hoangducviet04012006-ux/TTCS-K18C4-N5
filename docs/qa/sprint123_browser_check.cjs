const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.DEMO_BASE_URL;
assert(base, 'Set DEMO_BASE_URL explicitly; never reuse an unknown server');
const credentials = JSON.parse(fs.readFileSync('.sprint123-trial/credentials.local','utf8'));
const results = [];
async function login(page, account) {
  await page.goto(base);
  await page.locator('#login-username').fill(`s123_${account}@demo.local`);
  await page.locator('#login-password').fill(credentials[account]);
  await page.locator('#login-submit').click();
  await page.locator('#app-view').waitFor({state:'visible'});
  await page.waitForFunction(() => document.querySelector('#batch-page-label').textContent === 'Trang 1');
  await page.waitForFunction(() => !document.querySelector('#login-submit').disabled);
}
async function api(page, path, options) {
  return page.evaluate(async ({path,options}) => {
    try { return {status:200,data:await apiRequest(path,options)}; }
    catch (e) { return {status:e.status,error:e.message}; }
  },{path,options});
}
async function logout(page) { await page.locator('#btn-logout').click(); await page.locator('#login-view').waitFor({state:'visible'}); }
async function main() {
  const scope = await (await fetch(`${base}/demo-scope`)).json();
  assert.equal(scope.scope,'sprint123');
  assert(['demo_sprint123_north.db','demo_sprint123.db','demo_sprint123_realistic.db'].includes(scope.database_name));
  for (const channel of ['chrome','msedge']) {
    const browser = await chromium.launch({channel,headless:true});
    const context = await browser.newContext({viewport:{width:1440,height:960}});
    const page = await context.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    try {
      for (const [account, harvest, merge] of [['farm',true,false],['packing',false,true],['receiver',false,true],['transport',false,false],['distribution',false,false],['inspector',false,false],['admin',false,false],['org_admin',false,false]]) {
        await login(page,account);
        assert.equal(await page.locator('#batch-entry').evaluate(x=>!x.hidden),harvest);
        assert.equal(await page.locator('#btn-open-merge-batches').evaluate(x=>!x.hidden),merge);
        assert.equal(await page.locator('#farm-entry').evaluate(x=>!x.hidden),['farm','org_admin'].includes(account));
        const managesUsers = ['admin','org_admin'].includes(account);
        assert.equal(await page.locator('#nav-users').evaluate(x=>!x.hidden),managesUsers);
        const users = await api(page,'/users');
        assert.equal(users.status,managesUsers ? 200 : 403);
        if (account === 'org_admin') {
          const rows = Array.isArray(users.data) ? users.data : users.data.items;
          assert(rows.every(u=>u.organization_id===1));
        }
        const data = (await api(page,'/batches?limit=100')).data;
        const user = (await api(page,'/auth/me')).data;
        assert((await page.locator('#demo-profile').textContent()).includes(scope.database_name));
        assert.equal(await page.locator('#recall-card').isVisible(),false);
        if (account !== 'inspector') assert(data.every(b=>b.current_org_id === user.organization_id));
        if (account === 'inspector') {
          assert(new Set(data.map(b=>b.current_org_id)).size===3);
          assert.equal((await api(page,'/farms',{method:'POST',body:{name:'Forbidden',location:'Test',area:1,owner:'Test'}})).status,403);
          assert.equal((await api(page,'/auth/me')).status,200);
        }
        await logout(page);
        results.push({channel,test:`role:${account}`,passed:true});
      }
      await login(page,'farm');
      await page.locator('#farm-entry summary').click();
      const farmName=`QA-${channel}-${Date.now()}`;
      await page.locator('#farm-name').fill(farmName);
      await page.locator('#farm-location').fill('Thai Nguyen QA');
      await page.locator('#farm-area').fill('2.5');
      await page.locator('#farm-coordinates').fill('21.5583, 105.7725');
      await page.locator('#farm-owner').fill('QA Farmer');
      await page.locator('#farm-submit').click();
      await page.waitForFunction(name=>document.querySelector('#batch-farm-id').textContent.includes(name),farmName);
      const farm=(await api(page,'/farms')).data.find(f=>f.name===farmName);
      assert(farm);
      results.push({channel,test:'farm UI create',passed:true});
      await page.locator('#batch-entry summary').click();
      await page.locator('#batch-farm-id').selectOption(String(farm.id));
      await page.locator('#batch-product-id').selectOption({index:1});
      await page.locator('#batch-quantity').fill('100');
      await page.locator('#batch-harvest-date').fill('2026-10-09');
      let harvests=0;
      page.on('request',r=>{if(r.method()==='POST' && r.url()===`${base}/batches`)harvests++;});
      // Two synchronous submit events exercise the handler's in-flight guard.
      await page.locator('#batch-form').evaluate(form=>{form.requestSubmit(); form.requestSubmit();});
      await page.locator('#batch-success-banner').waitFor({state:'visible'});
      assert.equal(harvests,1);
      const harvested=(await api(page,'/batches')).data.find(b=>b.farm_id===farm.id);
      assert(harvested);
      assert.equal((await api(page,`/batches/${harvested.id}/integrity`)).data.is_valid,true);
      await page.locator('#batch-search-input').fill(harvested.code.toLowerCase());
      await page.waitForFunction(code=>document.querySelector('#batch-table-body').textContent.includes(code),harvested.code);
      const row=page.locator('#batch-table-body tr').filter({hasText:harvested.code});
      await row.locator('[data-action="split-batch"]').click();
      await page.locator('.split-child-qty').nth(0).fill('30');
      await page.locator('.split-child-qty').nth(1).fill('30');
      await page.locator('#btn-submit-split').click();
      await page.locator('#modal-split-success').waitFor({state:'visible'});
      const children=(await api(page,`/batches/${harvested.id}/summary`)).data.direct_children;
      assert.equal(children.length,2);
      assert.equal(Number((await api(page,`/batches/${harvested.id}`)).data.remaining_quantity),40);
      await page.locator('#btn-done-split-success').click();
      const integrity=(await api(page,`/batches/${harvested.id}/integrity`)).data;
      assert.equal(integrity.is_valid,true);
      results.push({channel,test:'harvest double submit, case search, split + integrity',passed:true});
      await logout(page);
      await login(page,'receiver');
      // Fresh lots have no historical/ancestor link to the receiving org yet.
      assert.equal((await api(page,`/batches/${harvested.id}`)).status,403);
      assert.equal((await api(page,`/batches/${harvested.id}/split`,{method:'POST',body:{items:[{quantity:1}]}})).status,403);
      assert.equal((await api(page,'/auth/me')).status,200);
      results.push({channel,test:'unrelated organization read/write denied; session preserved',passed:true});
      await logout(page);
      await login(page,'packing');
      await page.locator('#batch-search-input').fill('');
      await page.locator('#btn-reload').click();
      const all=(await api(page,'/batches?limit=100')).data;
      const childIds=children.map(x=>x.batch_id || x.id);
      assert(childIds.every(id=>all.some(x=>x.id===id)));
      for(const id of childIds) await page.locator(`.batch-select-checkbox[data-id="${id}"]`).check();
      await page.locator('#btn-open-merge-batches').click();
      await page.locator('.merge-parent-qty').nth(0).fill('20');
      await page.locator('.merge-parent-qty').nth(1).fill('20');
      await page.locator('#btn-submit-merge').click();
      await page.locator('#modal-merge-success').waitFor({state:'visible'});
      const mergedCode=(await page.locator('#merge-success-code-display').textContent()).trim();
      await page.locator('#btn-done-merge-success').click();
      const merged=(await api(page,`/batches?search=${mergedCode}`)).data[0];
      assert.equal(Number(merged.remaining_quantity),40);
      await page.locator('#batch-search-input').fill(mergedCode);
      await page.waitForFunction(code=>document.querySelector('#batch-table-body').textContent.includes(code),mergedCode);
      await page.locator('#batch-table-body tr').filter({hasText:mergedCode}).locator('[data-action="open-handover"]').click();
      const orgs=(await api(page,'/organizations')).data;
      const target=orgs.find(o=>o.code==='HTX-TG');
      await page.locator('#handover-to-org').selectOption(String(target.id));
      await page.locator('#btn-submit-handover').click();
      await page.locator('#modal-handover').waitFor({state:'hidden'});
      results.push({channel,test:'partial merge UI + handover pending',passed:true});
      await logout(page); await login(page,'receiver');
      const pending=(await api(page,'/handovers/pending')).data.find(h=>h.batch_id===merged.id);
      assert(pending);
      page.once('dialog',d=>d.accept());
      await page.locator(`[data-action="accept-handover"][data-id="${pending.id}"]`).click();
      await page.waitForFunction(id=>Array.from(document.querySelectorAll('#batch-table-body [data-action="view-details"]')).some(b=>Number(b.dataset.id)===id),merged.id);
      await page.locator(`[data-action="view-details"][data-id="${merged.id}"]`).click();
      await page.locator('#tab-btn-lineage').click();
      await page.locator('#detail-lineage-body').waitFor({state:'visible'});
      assert((await page.locator('#detail-lineage-body').textContent()).includes(harvested.code));
      await page.locator('#tab-btn-timeline').click();
      await page.locator('#btn-detail-verify-chain').click();
      await page.locator('#detail-timeline-valid-banner').waitFor({state:'visible'});
      await page.screenshot({path:`docs/qa/sprint123-${channel}-detail.png`,fullPage:true});
      results.push({channel,test:'receive UI, lineage, timeline, hash verification',passed:true});
      // 403 must preserve session; 401 must close details and return to login.
      assert.equal((await api(page,`/batches/${harvested.id}/split`,{method:'POST',body:{items:[{quantity:1}]}})).status,403);
      assert.equal((await api(page,'/auth/me')).status,200);
      await page.evaluate(()=>{location.hash='#pending-handovers-card';});
      await context.addCookies([{name:'session_id',value:'expired-demo-session',url:base}]);
      assert.equal((await api(page,'/auth/me')).status,401);
      await page.locator('#login-view').waitFor({state:'visible'});
      assert.equal(await page.locator('#modal-batch-details').evaluate(x=>x.hidden),true);
      await page.locator('#login-username').fill('s123_receiver@demo.local');
      await page.locator('#login-password').fill(credentials.receiver);
      await page.locator('#login-submit').click();
      await page.waitForFunction(()=>location.hash==='#pending-handovers-card');
      assert.equal(errors.length,0,errors.join('\n'));
      results.push({channel,test:'401 return destination / 403 retains session / no JS error',passed:true});
    } catch(e) { results.push({channel,passed:false,error:e.stack}); console.error(e); }
    finally { await browser.close(); fs.writeFileSync('docs/qa/sprint123_browser_results.json',JSON.stringify(results,null,2)); }
  }
  console.log(JSON.stringify(results,null,2));
  if(results.some(x=>!x.passed))process.exitCode=1;
}
main().catch(e=>{console.error(e);process.exitCode=1;});




