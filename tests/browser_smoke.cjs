// Optional browser check against scripts/demo_preview.py, using its demo owner button.
// Set NODE_PATH to your Playwright installation and STOCKLIST_BROWSER_OUTPUT to the demo folder.
const {chromium}=require('playwright');
const path=require('path');
(async()=>{
  const output=process.env.STOCKLIST_BROWSER_OUTPUT;
  if(!output)throw new Error('Set STOCKLIST_BROWSER_OUTPUT to the disposable demo folder.');
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1365,height:900},reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8501');
  await page.getByRole('heading',{name:'Sign in to Stocklist'}).waitFor({timeout:60000});
  for(const name of ['Owner demo','Warehouse demo','Accountant demo','Read-only demo'])
    await page.getByRole('button',{name:new RegExp(name+'$')}).waitFor();
  const logoLoaded=await page.getByRole('img',{name:'MCCIA logo',exact:true}).evaluate(img=>img.complete&&img.naturalWidth>0);
  if(!logoLoaded)throw new Error('MCCIA logo failed to load.');
  await page.screenshot({path:path.join(output,'demo-login.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(1200);
  const loginOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  await page.screenshot({path:path.join(output,'demo-login-mobile.png'),fullPage:true});
  await page.getByRole('button',{name:/Owner demo$/}).click();
  await page.getByRole('heading',{name:'Inventory overview'}).waitFor({timeout:60000});
  await page.getByTestId('stDataFrame').first().waitFor();
  await page.screenshot({path:path.join(output,'overview-mobile.png'),fullPage:true});
  const overviewOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  await page.setViewportSize({width:1365,height:900});
  await page.waitForTimeout(1200);
  if(await page.getByTestId('stSidebar').getAttribute('aria-expanded')==='false')
    await page.getByTestId('stExpandSidebarButton').click();
  await page.getByTestId('stMetricValue').first().waitFor();
  await page.getByTestId('stDataFrame').first().waitFor();
  const fontFamilies=await page.evaluate(()=>({body:getComputedStyle(document.body).fontFamily,heading:getComputedStyle(document.querySelector('h1')).fontFamily}));
  if(!fontFamilies.body.includes('Candara')||!fontFamilies.heading.includes('Segoe'))throw new Error('Brand font families are missing.');
  await page.screenshot({path:path.join(output,'overview.png'),fullPage:true});
  await page.getByTestId('stSidebar').getByTestId('stRadioOption').filter({hasText:'Assembly and jobs'}).click();
  await page.getByRole('heading',{name:'Assembly and jobs'}).waitFor();
  await page.getByTestId('stSelectbox').filter({hasText:'Finished product / kit'}).getByRole('combobox').click();
  await page.getByRole('option',{name:'Fabricated rack · DEMO-RACK',exact:true}).click();
  await page.getByRole('button',{name:'Record assembly',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'manufacturing.png'),fullPage:true});
  await page.getByTestId('stSidebar').getByTestId('stRadioOption').filter({hasText:'Reports'}).click();
  await page.getByRole('heading',{name:'Reports and accounting export'}).waitFor();
  await page.getByRole('button',{name:'Export this report'}).waitFor();
  await page.screenshot({path:path.join(output,'reports.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(1200);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  const offline=await browser.newPage({viewport:{width:390,height:844}});
  await offline.goto('file:///'+path.join(output,'offline.html').replaceAll('\\','/'));
  await offline.locator('#sku').fill('DEMO-SHEET');
  await offline.locator('#reason').fill('Offline production use');
  await offline.locator('#kind').selectOption('issue');
  await offline.getByRole('button',{name:'Save to offline queue'}).click();
  await offline.getByRole('heading',{name:'1 queued movements'}).waitFor();
  await offline.reload();
  await offline.getByRole('heading',{name:'1 queued movements'}).waitFor();
  await offline.screenshot({path:path.join(output,'offline-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1365,height:900});
  await page.waitForTimeout(1200);
  if(await page.getByTestId('stSidebar').getAttribute('aria-expanded')==='false')
    await page.getByTestId('stExpandSidebarButton').click();
  for(const [label,role] of [['Warehouse demo','warehouse'],['Accountant demo','accountant'],['Read-only demo','viewer']]){
    await page.getByRole('button',{name:/Sign out$/}).click();
    await page.getByRole('heading',{name:'Sign in to Stocklist'}).waitFor();
    await page.getByRole('button',{name:new RegExp(label+'$')}).click();
    await page.getByRole('heading',{name:'Inventory overview'}).waitFor({timeout:60000});
    await page.getByText('Demo '+role+' · '+role,{exact:true}).waitFor();
  }
  await page.getByRole('button',{name:/Sign out$/}).click();
  await page.getByRole('heading',{name:'Sign in to Stocklist'}).waitFor();
  if(await page.getByTestId('stDataFrame').count())throw new Error('Business tables remain after signing out.');
  console.log(JSON.stringify({browserErrors:errors,logoLoaded,fontFamilies,demoRoles:4,logout:'passed',mobileLoginOverflow:loginOverflow,mobileOverviewOverflow:overviewOverflow,mobileHorizontalOverflow:overflow,offlineQueuePersists:true}));
  if(errors.length||loginOverflow||overviewOverflow||overflow)throw new Error('Browser verification failed.');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
