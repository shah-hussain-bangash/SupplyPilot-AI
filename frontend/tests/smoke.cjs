/* Run against a freshly seeded local server. UI_TEST_PASSWORD must be set. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const password=process.env.UI_TEST_PASSWORD;if(!password)throw Error('Set UI_TEST_PASSWORD to the local seeded password');
 const base=process.env.BASE_URL||'http://127.0.0.1:8000';
 const out=path.resolve(process.env.UI_TEST_OUTPUT||'../evidence/ui');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/#/portal');await page.screenshot({path:path.join(out,'login.png'),fullPage:true});
 async function login(name){await page.getByLabel('Username',{exact:true}).fill(name);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.locator('nav').waitFor();}
 async function logout(){await page.getByRole('button',{name:'Sign out',exact:true}).click();await page.getByLabel('Username',{exact:true}).waitFor();}
 async function nav(name){await page.locator('nav button').filter({hasText:name}).click();await page.getByRole('heading',{name,exact:true,level:1}).waitFor();}
 async function done(){await page.getByRole('status').waitFor();await page.waitForFunction(()=>!document.querySelector('main button:disabled') || ![...document.querySelectorAll('main button')].some(b=>b.textContent==='Refresh'&&b.disabled));assert.equal(await page.getByRole('alert').count(),0);}
 await login('buyer');
 for(const name of ['Overview','RFQs','Documents','Compliance','Suppliers','Quotations','Inventory','Sourcing','Approvals','Purchase orders','Receiving','Invoices','Exceptions','Supplier portal','Forecasts','Customer quotes','Feedback','Audit'])await nav(name);
 await nav('Overview');await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
 await nav('Approvals');assert.equal(await page.getByRole('button',{name:'Approve',exact:true}).count(),0);
 await logout();await login('technical');await nav('Compliance');
 for(const supplier of ['gulf','desert']){await page.locator('tbody tr').filter({hasText:supplier}).getByRole('button',{name:'Certificate verified',exact:true}).click();await done();}
 await logout();await login('buyer');await nav('Sourcing');await page.getByRole('button',{name:'Lowest cost option',exact:true}).click();await done();
 assert((await page.locator('main').innerText()).includes('7250.00'));await page.screenshot({path:path.join(out,'sourcing.png'),fullPage:true});
 await logout();await login('manager');await nav('Approvals');await page.getByRole('button',{name:'Approve',exact:true}).click();await done();
 await logout();await login('buyer');await nav('Purchase orders');await page.getByRole('button',{name:'Queue exact approved order',exact:true}).click();await done();
 await page.getByRole('button',{name:'Simulate timeout',exact:true}).click();await done();assert((await page.locator('main').innerText()).includes('uncertain'));
 await page.getByRole('button',{name:'Reconcile',exact:true}).click();await done();await page.screenshot({path:path.join(out,'purchase-orders.png'),fullPage:true});
 await logout();await login('warehouse');await nav('Receiving');
 await page.getByLabel('Accepted pieces',{exact:true}).fill('30');await page.getByRole('button',{name:'Record inspected receipt',exact:true}).click();await done();
 await page.getByLabel('Allocation line index (starts at 0)',{exact:true}).fill('1');await page.getByLabel('Accepted pieces',{exact:true}).fill('25');await page.getByRole('button',{name:'Record inspected receipt',exact:true}).click();await done();
 await logout();await login('finance');await nav('Invoices');
 await page.getByRole('button',{name:'Match invoice',exact:true}).click();await done();
 await page.getByLabel('Allocation line index',{exact:true}).fill('1');await page.getByLabel('Supplier invoice number',{exact:true}).fill('INV-002');await page.getByLabel('Invoice pieces',{exact:true}).fill('25');await page.getByLabel('Material unit price AED',{exact:true}).fill('128');await page.getByRole('button',{name:'Match invoice',exact:true}).click();await done();
 await logout();await login('buyer');await nav('Purchase orders');await page.getByRole('button',{name:'Close fulfilled order',exact:true}).click();await done();
 await nav('Overview');assert((await page.locator('main').innerText()).includes('Closed cases'));await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 await logout();await login('supplier-gulf');assert.equal(await page.locator('nav button').count(),2);assert.equal(await page.locator('tbody tr').filter({hasText:'desert'}).count(),0);
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'ui-test-result.json'),JSON.stringify({passed:true,screen_count:18,workflow:'technical review -> checked plan -> approval -> timeout -> reconcile -> receipts -> matched invoices -> closure',roles:['buyer','technical','manager','warehouse','finance','supplier'],browser_errors:errors},null,2));
 await browser.close();console.log('UI smoke passed: 18 screens, six roles, complete case and timeout recovery.');
})().catch(e=>{console.error(e);process.exitCode=1;});
