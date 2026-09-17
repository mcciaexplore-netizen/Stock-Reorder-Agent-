// Read-only browser smoke test against the sample business demo.
const {chromium}=require('playwright');
const path=require('path');
(async()=>{
  const output=process.env.STOCKLIST_BROWSER_OUTPUT;
  if(!output)throw new Error('Set STOCKLIST_BROWSER_OUTPUT to the disposable demo folder.');
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1365,height:900},reducedMotion:'reduce'});
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    await page.goto('http://127.0.0.1:8501');
    await page.getByRole('button',{name:/Owner demo$/}).waitFor({timeout:60000});
    await page.getByRole('button',{name:/Owner demo$/}).click();
    await page.getByRole('heading',{name:'Inventory overview'}).waitFor({timeout:60000});
    const screens=[['Customer orders','Customer quotations and sales orders'],
      ['Locations and reservations','Locations and reservations'],['Tracking and units','Tracking and units'],
      ['Quotations and bills','Quotations and supplier bills'],['Quality checks','Quality checks']];
    const checks=[];
    const groups={
      'Customer orders':['Sales','Customer quotations and orders'],
      'Locations and reservations':['Stock','Stock locations'],
      'Tracking and units':['Products','Product setup'],
      'Quotations and bills':['Purchases','Suppliers, bills and inspections'],
      'Quality checks':['Purchases','Suppliers, bills and inspections'],
    };
    for(const [nav,title] of screens){
      const back=page.getByRole('button',{name:/Back to /});
      if(await back.count())await back.click();
      const [parent,group]=groups[nav];
      await page.getByTestId('stSidebar').getByTestId('stRadioOption').filter({hasText:parent}).click();
      await page.getByText(group,{exact:true}).click();
      await page.getByRole('button',{name:new RegExp(nav+'$')}).click();
      const heading=page.getByRole('heading',{name:title,exact:true});
      await heading.waitFor({timeout:30000});await heading.scrollIntoViewIfNeeded();
      await page.locator('[data-testid="stDataFrame"]:visible').first().waitFor();
      if(await page.getByTestId('stException').count())throw new Error(await page.getByTestId('stException').innerText());
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
      if(overflow)throw new Error('Desktop overflow on '+nav);
      checks.push({page:nav,tables:await page.getByTestId('stDataFrame').count(),overflow});
      await page.screenshot({path:path.join(output,nav.toLowerCase().replaceAll(' ','-')+'.png'),fullPage:true});
    }
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('heading',{name:screens.at(-1)[1]}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'quality-checks-mobile.png'),fullPage:true});
    const mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
    if(errors.length||mobileOverflow)throw new Error(JSON.stringify({errors,mobileOverflow}));
    console.log(JSON.stringify({checks,mobileOverflow,browserErrors:errors}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
