/* Fresh synthetic demo only; launched by scripts/test_browser.py. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const password=process.env.UI_TEST_PASSWORD;
  const base=process.env.BASE_URL;
  const out=process.env.UI_TEST_OUTPUT;
  assert(password && /^http:\/\/127\.0\.0\.1:\d+$/.test(base) && out,
    'Use the isolated browser runner to provide the local test environment');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const guard=setTimeout(()=>{console.error('Browser suite exceeded four minutes');browser.close().finally(()=>{process.exitCode=1;});},240000);
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.url().startsWith(base+'/api/') && r.status()>=500)errors.push('API '+r.status()+' '+new URL(r.url()).pathname);});
  function pass(label){checks.push(label);console.log('PASS: '+label);}
  async function ready(){
    await page.waitForFunction(()=>{const b=[...document.querySelectorAll('main button')].find(x=>x.textContent==='Refresh');return b && !b.disabled;});
    assert.equal(await page.getByRole('alert').count(),0);
  }
  async function login(name){
    await page.getByLabel('Username',{exact:true}).fill(name);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.locator('.shell').waitFor();await ready();
    assert((await page.locator('.account').innerText()).includes(name));
    pass('Browser login succeeds for '+name);
  }
  async function logout(){await page.getByRole('button',{name:'Sign out',exact:true}).click();await page.getByLabel('Username',{exact:true}).waitFor();}
  async function nav(name){const menu=page.getByRole('button',{name:'Menu',exact:false});if(await menu.isVisible() && await menu.getAttribute('aria-expanded')==='false')await menu.click();await page.locator('.shell nav button').filter({hasText:name}).click();await page.getByRole('heading',{name,exact:true,level:1}).waitFor();await ready();}
  async function mutate(button){
    await button.scrollIntoViewIfNeeded();
    const [response]=await Promise.all([
      page.waitForResponse(r=>r.url().startsWith(base+'/api/v1/') && r.request().method()==='POST'),
      button.click()
    ]);
    assert(response.ok(),'Mutation failed: '+response.status()+' '+new URL(response.url()).pathname);
    const saved=await response.json();
    await page.getByRole('status').waitFor();
    // A previous detail/status can still be mounted while React refreshes the lists.
    await page.waitForFunction(expected=>{
      const refresh=[...document.querySelectorAll('main button')].find(x=>x.textContent==='Refresh');
      const pre=document.querySelector('.detail pre');
      return refresh && !refresh.disabled && pre && JSON.stringify(JSON.parse(pre.textContent))===JSON.stringify(expected);
    },saved);
    await ready();return saved;
  }
  const button=name=>page.getByRole('button',{name,exact:true});
  async function inspect(row,expected){
    await row.getByRole('button',{name:'Inspect',exact:true}).click();
    await page.waitForFunction(({id,revision})=>{
      const pre=document.querySelector('.detail pre');if(!pre)return false;
      const shown=JSON.parse(pre.textContent);return shown.id===id && shown.revision===revision;
    },{id:expected.id,revision:expected.revision});
    return JSON.parse(await page.locator('.detail pre').innerText());
  }
  try{
    await page.goto(base+'/#/portal');
    assert(await page.getByRole('heading',{name:'Welcome back',exact:true}).isVisible());
    assert(await page.locator('.signin-story').evaluate(el=>getComputedStyle(el).backgroundImage.includes('signin-warehouse.webp')));
    assert(await page.getByLabel('Username',{exact:true}).evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=16));
    await page.getByLabel('Password',{exact:true}).fill('visibility-test');
    await button('Show password').click();assert.equal(await page.getByLabel('Password',{exact:true}).getAttribute('type'),'text');
    await button('Hide password').click();assert.equal(await page.getByLabel('Password',{exact:true}).getAttribute('type'),'password');
    pass('Redesigned sign-in has readable controls, warehouse imagery and password visibility toggle');
    await page.screenshot({path:path.join(out,'signin-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(out,'signin-mobile.png'),fullPage:true});
    pass('Sign-in fits a 390px mobile viewport without page overflow');
    await page.setViewportSize({width:1440,height:1000});
    await login('buyer');
    assert.equal(await page.locator('.portal-stats .portal-stat strong').nth(1).innerText(),'0');
    assert(await page.getByRole('heading',{name:'No purchase orders yet'}).isVisible());
    pass('Overview displays actual empty order data without invented demonstration totals');
    await page.evaluate(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'instant'}));
    await button('Create RFQ').click();await page.getByRole('heading',{name:'RFQs',exact:true,level:1}).waitFor();await nav('Overview');
    await page.waitForFunction(()=>window.scrollY===0);
    pass('Page navigation resets the workspace to its heading');
    await button('Review documents').click();await page.getByRole('heading',{name:'Documents',exact:true,level:1}).waitFor();await nav('Overview');
    pass('New overview actions open the existing RFQ and document workflows');
    const screens=['Overview','RFQs','Documents','Compliance','Suppliers','Quotations','Inventory','Sourcing','Approvals','Purchase orders','Receiving','Invoices','Exceptions','Supplier portal','Forecasts','Customer quotes','Feedback','Audit'];
    for(const screen of screens){
      await nav(screen);
      if(screen!=='Overview'){
        const image=page.locator('.portal-page-image img');
        await image.evaluate(img=>img.decode());
        assert(await image.evaluate(img=>{const banner=img.closest('.portal-page-banner').getBoundingClientRect();const picture=img.getBoundingClientRect();return img.naturalWidth>0 && Math.abs(picture.width-(banner.width-2))<2 && Math.abs(picture.height-(banner.height-2))<2;}));
        assert((await page.locator('.portal-page-description').innerText()).length>20);
      }
      if(['Documents','Compliance','Inventory','Sourcing','Receiving','Invoices'].includes(screen))
        await page.screenshot({path:path.join(out,screen.toLowerCase()+'-desktop.png'),fullPage:true});
    }
    pass('Every inner portal page loads a full-width photograph and readable page introduction');
    pass('All 18 buyer screens load without an alert');
    await nav('Approvals');assert.equal(await button('Approve').count(),0);pass('Buyer cannot approve purchasing');
    await logout();await login('technical');await nav('Compliance');
    for(const supplier of ['gulf','desert'])await mutate(page.locator('tbody tr').filter({hasText:supplier}).getByRole('button',{name:'Certificate verified',exact:true}));
    pass('Technical review accepts both synthetic supplier certificates');
    await logout();await login('buyer');await nav('Sourcing');await mutate(button('Lowest cost option'));
    assert((await page.locator('main').innerText()).includes('7250.00'));pass('Sourcing displays AED 7250');
    await logout();await login('manager');await nav('Approvals');await mutate(button('Approve'));pass('Manager approves the scenario');
    await logout();await login('buyer');await nav('Purchase orders');await mutate(button('Queue exact approved order'));
    await mutate(button('Simulate timeout'));assert((await page.locator('main').innerText()).includes('uncertain'));pass('Timeout displays uncertain execution');
    await mutate(button('Reconcile'));assert((await page.locator('main').innerText()).includes('confirmed'));pass('Reconciliation confirms the purchase');
    await logout();await login('warehouse');await nav('Receiving');
    await page.getByLabel('Accepted pieces',{exact:true}).fill('30');const savedReceipt=await mutate(button('Record inspected receipt'));
    const receipt=await inspect(page.locator('tbody tr').filter({hasText:'30'}),savedReceipt);
    assert.equal(receipt.data.accepted,30);assert.equal(receipt.data.supplier_id,'gulf');pass('Gulf receipt details retain 30 accepted pieces');
    await logout();await login('finance');await nav('Invoices');await mutate(button('Match invoice'));
    await page.getByLabel('Allocation line index',{exact:true}).fill('1');
    await page.getByLabel('Supplier invoice number',{exact:true}).fill('INV-002');
    await page.getByLabel('Invoice pieces',{exact:true}).fill('25');
    await page.getByLabel('Material unit price AED',{exact:true}).fill('128.00');const savedInvoice=await mutate(button('Match invoice'));
    let invoice=await inspect(page.locator('tbody tr').filter({hasText:'INV-002'}),savedInvoice);
    assert.equal(invoice.data.status,'mismatch');assert.equal(invoice.data.quantity,25);pass('Desert invoice is mismatched before receiving');
    const invoiceId=invoice.id;
    await logout();await login('warehouse');await nav('Receiving');
    await page.getByLabel('Allocation line index (starts at 0)',{exact:true}).fill('1');
    await page.getByLabel('Accepted pieces',{exact:true}).fill('25');await mutate(button('Record inspected receipt'));
    await logout();await login('finance');await nav('Invoices');
    const recheckedInvoice=await mutate(page.locator('tbody tr').filter({hasText:'INV-002'}).getByRole('button',{name:'Recheck invoice',exact:true}));
    invoice=await inspect(page.locator('tbody tr').filter({hasText:'INV-002'}),recheckedInvoice);
    assert.equal(invoice.id,invoiceId);assert.equal(invoice.revision,2);assert.equal(invoice.data.status,'matched');
    assert.equal(invoice.data.unit_price,'128.00');assert.equal(invoice.data.assessment_history[0].data.status,'mismatch');
    pass('Invoice recheck preserves identity, exact price and mismatch history');
    await logout();await login('buyer');await nav('Purchase orders');const closedOrder=await mutate(button('Close fulfilled order'));
    const order=await inspect(page.locator('tbody tr').filter({hasText:'closed'}),closedOrder);
    assert.equal(order.data.status,'closed');assert.equal(order.data.total,'7250.00');
    assert.equal(order.data.lines.reduce((n,x)=>n+x.accepted,0),55);pass('Closed order retains AED 7250 and 55 accepted pieces');
    await page.screenshot({path:path.join(out,'closed-order.png'),fullPage:true});
    await nav('Overview');
    assert.deepEqual(await page.locator('.portal-stats .portal-stat strong').allTextContents(),['1','1','1']);
    assert((await page.locator('.portal-order-card').innerText()).includes('7,250.00'));
    assert((await page.locator('.portal-fulfillment').innerText()).includes('55 pieces'));
    await page.waitForFunction(()=>window.scrollY===0);
    await page.screenshot({path:path.join(out,'overview-desktop.png'),fullPage:true});
    pass('Overview reflects the real closed simulator order, AED 7250 and 55 accepted pieces');
    await page.setViewportSize({width:390,height:844});await nav('Overview');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'Menu',exact:false}).click();
    assert.equal(await page.getByRole('button',{name:'Menu',exact:false}).getAttribute('aria-expanded'),'true');
    await nav('Documents');
    await page.locator('.portal-page-image img').evaluate(img=>img.decode());
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(out,'documents-mobile.png'),fullPage:true});
    pass('Inner-page photography and document forms fit the mobile viewport');
    await nav('Overview');
    pass('Mobile menu opens and navigates existing screens without page overflow');
    assert(await page.locator('.shell').isVisible());await page.screenshot({path:path.join(out,'mobile-overview.png'),fullPage:true});pass('Workspace remains accessible at a mobile viewport');
    await page.setViewportSize({width:1440,height:1000});await logout();await login('supplier-gulf');
    assert.equal(await page.locator('.shell nav button').count(),2);
    assert.equal(await page.locator('tbody tr').filter({hasText:'desert'}).count(),0);pass('Supplier sees restricted navigation and no competitor quotations');
    await logout();await login('auditor');await nav('Audit');
    assert.equal(await page.locator('tbody tr').filter({hasText:'order.closed'}).count(),1);pass('Auditor sees the order closure event');
    assert.deepEqual(errors,[]);pass('No browser exceptions or server errors occurred');
    fs.writeFileSync(path.join(out,'ui-test-result.json'),JSON.stringify({passed:true,checks_passed:checks.length,checks,roles:['buyer','technical','manager','warehouse','finance','supplier-gulf','auditor'],screen_count:18,database:'temporary SQLite',browser_errors:errors},null,2));
    console.log('BROWSER ACCEPTANCE PASSED: '+checks.length+' checks');
  }finally{clearTimeout(guard);await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
