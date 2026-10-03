// TEST HARNESS ONLY: account is synthetic; product API/TTS and source UI are real.
const {app, BrowserWindow, ipcMain} = require('electron');
const fs=require('node:fs'), path=require('node:path'), cp=require('node:child_process');
const root=path.resolve(__dirname,'../../../..');
const run=path.join(root,'.local/urun',`ui-integration-${Date.now()}`); fs.mkdirSync(run,{recursive:true});
app.setPath('userData',path.join(run,'electron-data')); app.disableHardwareAcceleration();
const {validateRequest}=require(path.join(root,'apps/desktop/gui/electron/ipc-policy.cjs'));
let child, win, signed=false; const receipt={test_auth:'synthetic harness only',database:path.join(run,'data'),checks:[],errors:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,limit=15000){let start=Date.now();while(Date.now()-start<limit){if(await fn())return;await sleep(150);}throw Error('Wait timed out');}
function check(name,truth){receipt.checks.push({name,passed:!!truth});if(!truth)throw Error(name);}
async function js(code){return win.webContents.executeJavaScript(code,true);}
async function snap(name){await sleep(400);fs.writeFileSync(path.join(run,name+'.png'),(await win.webContents.capturePage()).toPNG());}
app.whenReady().then(async()=>{
 try{
  child=cp.spawn(path.join(root,'apps/desktop/.venv/Scripts/python.exe'),[path.join(__dirname,'qa-product-server.py'),run],{cwd:path.join(root,'apps/desktop'),windowsHide:true,env:{...process.env,PYTHONPATH:path.join(root,'apps/desktop/core'),RASATHANE_SESSION_TOKEN:''},stdio:['ignore','pipe','pipe']});
  child.stderr.on('data',d=>fs.appendFileSync(path.join(run,'server.stderr.log'),d));
  await wait(()=>fs.existsSync(path.join(run,'server.json')));
  const {port,workspace}=JSON.parse(fs.readFileSync(path.join(run,'server.json')));
  const origin=`http://127.0.0.1:${port}`;
  await wait(async()=>{try{return (await fetch(origin+'/gui/health')).ok;}catch{return false;}});
  ipcMain.handle('rasathane:account-status',()=>({state:signed?'signed_in':'signed_out',scope:[]}));
  ipcMain.handle('rasathane:open-account',()=>{signed=true;win.webContents.send('rasathane:account-change',{state:'signed_in',scope:[]});return {};});
  ipcMain.handle('rasathane:sign-out',()=>{signed=false;win.webContents.send('rasathane:account-change',{state:'signed_out',scope:[]});return {signedOut:true,remoteRevoked:true};});
  ipcMain.handle('rasathane:setup-status',()=>({ready:true,state:'ready',models:[]}));
  ipcMain.handle('rasathane:entitlement',()=>({durum:'aktif',products:[]}));
  ipcMain.handle('rasathane:request',async(_,route,options)=>{
   if(!signed)throw Error('Test authenticated boundary: login required');
   const r=validateRequest(route,options);receipt.requests??=[];receipt.requests.push(r.route);
   const response=await fetch(origin+r.route,{method:r.method,body:r.body,headers:{'Content-Type':'application/json'}});
   const contentType=response.headers.get('content-type'); const bytes=Buffer.from(await response.arrayBuffer());
   return {ok:response.ok,status:response.status,contentType,...(contentType.includes('application/json')?{data:JSON.parse(bytes)}:{base64:bytes.toString('base64')})};
  });
  win=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{preload:path.join(root,'apps/desktop/gui/electron/preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false,backgroundThrottling:false,offscreen:true}});
  win.webContents.setAudioMuted(true);
  win.webContents.on('console-message',(_,level,message)=>{if(level>=2)receipt.errors.push(message);});
  await win.loadURL(origin+'/index.html'); await sleep(400);
  check('logged out blocks product screens',await js(`document.body.classList.contains('session-locked') && document.querySelector('#app-main').inert && !document.querySelector('#giris-ekrani').hidden`));
  check('logged out sends no data requests',!receipt.requests?.length); await snap('01-locked');
  await js(`localStorage.setItem('rasathane-setup-v1','complete');document.querySelector('#giris-baslat').click()`);
  await wait(()=>js(`document.querySelector('#akis-liste').textContent.includes('Sentetik QA haberi')`));
  await js(`for(const d of document.querySelectorAll('dialog[open]')) d.close();document.querySelector('[data-gorunum="akis"]').click()`);
  check('synthetic login unlocks real feed',await js(`!document.body.classList.contains('session-locked')`));
  await sleep(500);
  await js(`document.querySelector('.news-summary-control button').click()`);
  await wait(()=>js(`document.querySelector('.news-summary').textContent.includes('Başvuru süresi otuz gündür')`)); await snap('02-summary');
  await js(`document.querySelector('.news-summary button').click()`);
  await wait(()=>js(`!!document.querySelector('.news-summary audio').getAttribute('src')`),30000);
  await wait(()=>js(`document.querySelector('.news-summary audio').readyState >= 2`),10000);
  check('real Windows WAV playable',await js(`document.querySelector('.news-summary audio').duration > 0`));
  await snap('02b-speech');
  await js(`window.__qaOldAudio=document.querySelector('.news-summary audio'); document.querySelector('.news-summary-control button').click()`);
  await wait(()=>js(`document.querySelector('.news-summary button')?.textContent==='Sesli oku'`));
  check('repeating summary stops and releases old audio',await js(`window.__qaOldAudio.paused && !window.__qaOldAudio.getAttribute('src')`));
  await js(`window.__qaMetadata=Array.from(document.querySelectorAll('#akis-liste .record')).find(n=>n.querySelector('h3')?.textContent==='Sentetik karar künyesi');window.__qaMetadata.querySelector('.news-summary-control button').click()`);
  await wait(()=>js(`window.__qaMetadata.querySelector('.news-summary').textContent.includes('yeterli metin yok')`));
  check('unavailable summary has no null text or speak action',await js(`!window.__qaMetadata.querySelector('.news-summary').textContent.includes('null') && !window.__qaMetadata.querySelector('.news-summary button')`));
  await js(`document.querySelector('[data-gorunum="arastir"]').click();document.querySelector('#arastir-web').checked=false;document.querySelector('#arastir-sorgu').value='Başvuru süresi nedir?';document.querySelector('#arastir-form').requestSubmit()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===1 && !document.querySelector('#arastir-btn').disabled`),20000);
  check('first source-bound chat answer',await js(`document.querySelector('.chat-assistant').textContent.includes('otuz')`));
  await js(`document.querySelector('#arastir-sorgu').value='Başvurular nasıl yapılır?';document.querySelector('#arastir-form').requestSubmit()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===2 && !document.querySelector('#arastir-btn').disabled`),20000);
  check('two conversational turns',await js(`document.querySelectorAll('.chat-user').length===2 && document.querySelectorAll('.chat-assistant').length===2`)); await snap('03-chat');
  check('follow-up finds existing source evidence',await js(`Array.from(document.querySelectorAll('.chat-assistant')).at(-1).textContent.includes('çevrimiçi')`));
  win.reload(); await new Promise(r=>win.webContents.once('did-finish-load',r));
  await wait(()=>js(`document.querySelectorAll('.chat-history-item').length>0`));
  await js(`for(const d of document.querySelectorAll('dialog[open]')) d.close();document.querySelector('[data-gorunum="arastir"]').click();document.querySelector('.chat-history-item').click()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===2`));
  check('conversation survives reload',await js(`document.querySelectorAll('.chat-user').length===2`)); await snap('04-persisted');
  await js(`Array.from(document.querySelectorAll('.chat-history-item')).find(n=>n.textContent.startsWith('Uzun QA geçmişi')).click()`);
  await wait(()=>js(`document.querySelectorAll('.chat-message').length===100`));
  check('long history opens newest 50 turns',await js(`document.querySelector('.chat-user').textContent.includes('tur 06') && Array.from(document.querySelectorAll('.chat-assistant')).at(-1).textContent.includes('55') && !!document.querySelector('.chat-older')`));
  check('opened conversation locks its workspace selector',await js(`document.querySelector('#arastir-alan').disabled && document.querySelector('#arastir-alan').value===${JSON.stringify(workspace)}`));
  await js(`document.querySelector('#arastir-sonuc').scrollTop=0`); await snap('04b-history-page');
  await js(`document.querySelector('.chat-older').click()`);
  await wait(()=>js(`document.querySelectorAll('.chat-message').length===110`));
  check('older page restores all 55 turns in order',await js(`document.querySelectorAll('.chat-user').length===55 && document.querySelectorAll('.chat-assistant').length===55 && document.querySelector('.chat-user').textContent.includes('tur 01') && !document.querySelector('.chat-older')`));
  check('history requested real cursor API',receipt.requests.some(route=>route.includes('/conversations/') && route.includes('?before=')));
  await js(`document.querySelector('#arastir-sonuc').scrollTop=0`); await snap('04c-history-complete');
  await js(`window.rasathane.signOut()`); await sleep(400);
  check('logout locks and clears news',await js(`document.body.classList.contains('session-locked') && document.querySelector('#app-main').inert && !document.querySelector('#akis-liste').textContent`));
  check('logout clears conversation',await js(`!document.querySelector('.chat-assistant')`)); await snap('05-logout');
  receipt.ok=true;
 }catch(e){receipt.ok=false;receipt.failure=e.stack;if(win){receipt.dom=await js(`document.body.innerText`).catch(()=>null);await snap('failure').catch(()=>{});}}
 finally{
  if(child){
   receipt.owned_server_pid=child.pid;
   if(child.exitCode===null){
    await new Promise(resolve=>cp.execFile('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>resolve()));
    try{await wait(()=>child.exitCode!==null || child.signalCode!==null,5000);}catch{receipt.ok=false;receipt.shutdown_error='Owned server did not exit';}
   }
   receipt.owned_server_exited=child.exitCode!==null || child.signalCode!==null;
  }
  fs.writeFileSync(path.join(run,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify({run,ok:receipt.ok,failure:receipt.failure,checks:receipt.checks}));win?.destroy();app.exit(receipt.ok?0:1);
 }
});
