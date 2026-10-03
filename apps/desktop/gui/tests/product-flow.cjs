// TEST HARNESS ONLY: account is synthetic; product API/TTS and source UI are real.
const {app, BrowserWindow, ipcMain, safeStorage, protocol, net} = require('electron');
const crypto = require('node:crypto');
const fs=require('node:fs'), path=require('node:path'), cp=require('node:child_process');
const {pathToFileURL}=require('node:url');
const nodeNet=require('node:net');
const root=path.resolve(__dirname,'../../../..');
const frozenExe=process.env.RASATHANE_QA_SIDECAR || '';
const uiRoot=process.env.RASATHANE_QA_UI || path.join(root,'apps/desktop/gui/ui');
const frozen=!!frozenExe;
if(frozen)protocol.registerSchemesAsPrivileged([{scheme:'rasathane',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:true}}]);
const run=path.join(root,'.local/urun',`ui-integration-${Date.now()}`); fs.mkdirSync(run,{recursive:true});
app.setPath('userData',path.join(run,'electron-data')); app.disableHardwareAcceleration();
const {validateRequest}=require(path.join(root,'apps/desktop/gui/electron/ipc-policy.cjs'));
let child, win, account, gate; const receipt={test_auth:'real native account/PKCE/DPAPI with synthetic remote OTP transport; no live email',database:path.join(run,'data'),checks:[],errors:[]};
const sessionToken=crypto.randomBytes(32).toString('hex');
const localHeaders={'Content-Type':'application/json',Origin:'rasathane://app','X-Rasathane-Session':sessionToken};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,limit=15000){let start=Date.now();while(Date.now()-start<limit){if(await fn())return;await sleep(150);}throw Error('Wait timed out');}
function check(name,truth){receipt.checks.push({name,passed:!!truth});if(!truth)throw Error(name);}
async function js(code){return win.webContents.executeJavaScript(code,true);}
async function snap(name){await sleep(400);fs.writeFileSync(path.join(run,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function freePort(){return new Promise((resolve,reject)=>{const server=nodeNet.createServer();server.once('error',reject);server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});}
app.whenReady().then(async()=>{
 try{
  if(frozen && (!path.isAbsolute(frozenExe) || !fs.statSync(frozenExe).isFile() || !path.isAbsolute(uiRoot) || !fs.existsSync(path.join(uiRoot,'index.html'))))throw Error('QA sidecar and UI paths must be existing absolute paths');
  receipt.mode=frozen?'frozen sidecar with isolated seeded database':'source product server';
  receipt.ui=uiRoot;
  if(frozen)receipt.sidecar={path:frozenExe,sha256:crypto.createHash('sha256').update(fs.readFileSync(frozenExe)).digest('hex')};
  child=cp.spawn(path.join(root,'apps/desktop/.venv/Scripts/python.exe'),[path.join(__dirname,'qa-product-server.py'),run,...(frozen?['--seed-only']:[])],{cwd:path.join(root,'apps/desktop'),windowsHide:true,env:{...process.env,PYTHONPATH:path.join(root,'apps/desktop/core'),RASATHANE_SESSION_TOKEN:''},stdio:['ignore','pipe','pipe']});
  child.stderr.on('data',d=>fs.appendFileSync(path.join(run,'server.stderr.log'),d));
  let port,workspace;
  if(frozen){
   const seedExit=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});
   if(seedExit!==0)throw Error('QA fixture seeding failed');
   ({workspace}=JSON.parse(fs.readFileSync(path.join(run,'seed.json'))));port=await freePort();
   child=cp.spawn(frozenExe,['http'],{cwd:path.dirname(frozenExe),windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,RASATHANE_SIDECAR_PORT:String(port),RASATHANE_SESSION_TOKEN:sessionToken,RASATHANE_DATA_DIR:path.join(run,'data'),YT_CHECKPOINT_DIR:path.join(run,'data'),YT_OUTPUT_BASE:path.join(run,'workspace'),RASATHANE_MOTOR_DIR:path.join(run,'motor'),RASATHANE_LOG_DIR:path.join(run,'logs'),YT_TTS_CLOUD:'0',YT_CLOUD_VERDICT:'0'}});
   child.stderr.on('data',d=>fs.appendFileSync(path.join(run,'frozen.stderr.log'),d));
   child.stdout.on('data',d=>fs.appendFileSync(path.join(run,'frozen.stdout.log'),d));
   child.once('error',error=>{receipt.spawn_error=error.message;});
   protocol.handle('rasathane',request=>{const url=new URL(request.url);const file=path.resolve(uiRoot,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));if(url.host!=='app' || !file.startsWith(path.resolve(uiRoot)+path.sep))return new Response('Not found',{status:404});return net.fetch(pathToFileURL(file).href);});
  }else{
   await wait(()=>fs.existsSync(path.join(run,'server.json')));
   ({port,workspace}=JSON.parse(fs.readFileSync(path.join(run,'server.json'))));
  }
  const origin=`http://127.0.0.1:${port}`;
  await wait(async()=>{try{return (await fetch(origin+'/gui/health',{headers:frozen?localHeaders:{}})).ok;}catch{return false;}},frozen?90000:15000);
  let requested;
  account = require('../electron/account.cjs').createAccount({userData:app.getPath('userData'),safeStorage,openExternal:()=>{throw Error('Native email login must not open a browser');},transport:async(url, options)=>{
    const input=JSON.parse(options.body || '{}');
    if(url.endsWith('/email/request')){
      requested=input;
      return Response.json({challenge_id:'eotp_'+'a'.repeat(43),expires_at:new Date(Date.now()+300000).toISOString(),resend_after_seconds:60});
    }
    if(url.endsWith('/email/verify')){
      check('native verification preserves email/device and PKCE',input.email===requested.email && input.device_id===requested.device_id && crypto.createHash('sha256').update(input.code_verifier).digest('base64url')===requested.code_challenge);
      if(input.code!=='123456')return Response.json({code:'OTP_GECERSIZ'},{status:400});
      return Response.json({schema_version:'1.1',device_id:input.device_id,durum:'aktif',session_id:'dses_'+'b'.repeat(16),access_token:'at_'+'c'.repeat(43),refresh_token:'rt_'+'d'.repeat(43),scope:['desktop','urun:rasathane'],access_sure_sonu:new Date(Date.now()+600000).toISOString(),refresh_sure_sonu:new Date(Date.now()+3600000).toISOString()});
    }
    if(url.endsWith('/revoke'))return Response.json({revoked:true});
    throw Error('Unexpected synthetic auth route');
  }});
  gate=require('../electron/auth-gate.cjs').createAuthGate(account);
  account.subscribe(state=>win?.webContents.send('rasathane:account-change',state));
  ipcMain.handle('rasathane:account-status',()=>account.checkSession());
  ipcMain.handle('rasathane:send-login-code',(_,email)=>account.sendLoginCode(email));
  ipcMain.handle('rasathane:verify-login-code',(_,code)=>account.verifyLoginCode(code));
  ipcMain.handle('rasathane:cancel-login',()=>account.cancelLogin());
  ipcMain.handle('rasathane:sign-out',async()=>{const result=await account.signOut();if(frozen)await fetch(origin+'/api/product/service-session',{method:'POST',headers:localHeaders,body:JSON.stringify({access_token:null})});return result;});
  ipcMain.handle('rasathane:setup-status',()=>({ready:true,state:'ready',models:[]}));
  ipcMain.handle('rasathane:entitlement',()=>({durum:'aktif',products:[]}));
  ipcMain.handle('rasathane:request',async(_,route,options)=>gate.run(async lease=>{
   const r=validateRequest(route,options);receipt.requests??=[];receipt.requests.push(r.route);
   if(frozen){const accessToken=await account.serviceAccessToken();lease.assertCurrent();const session=await fetch(origin+'/api/product/service-session',{method:'POST',headers:localHeaders,body:JSON.stringify({access_token:accessToken}),signal:lease.signal});if(!session.ok)throw Error('Frozen native session setup failed');}
   const response=await fetch(origin+r.route,{method:r.method,body:r.body,headers:frozen?localHeaders:{'Content-Type':'application/json'},signal:lease.signal});
   const contentType=response.headers.get('content-type'); const bytes=Buffer.from(await response.arrayBuffer());
   return {ok:response.ok,status:response.status,contentType,...(contentType.includes('application/json')?{data:JSON.parse(bytes)}:{base64:bytes.toString('base64')})};
  }));
  win=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{preload:path.join(root,'apps/desktop/gui/electron/preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false,backgroundThrottling:false,offscreen:true}});
  win.webContents.setAudioMuted(true);
  win.webContents.on('console-message',(_,level,message)=>{if(level>=2)receipt.errors.push(message);});
  await win.loadURL(frozen?'rasathane://app/index.html':origin+'/index.html'); await sleep(400);
  check('logged out blocks product screens',await js(`document.body.classList.contains('session-locked') && document.querySelector('#app-main').inert && !document.querySelector('#giris-ekrani').hidden`));
  check('logged out sends no data requests',!receipt.requests?.length); await snap('01-locked');
  await js(`localStorage.setItem('rasathane-setup-v1','complete');document.querySelector('#giris-email').value='qa@example.com';document.querySelector('#giris-email-form').requestSubmit()`);
  await wait(()=>js(`!document.querySelector('#giris-kod-form').hidden`));
  check('sent code keeps product locked and resend waits',await js(`document.body.classList.contains('session-locked') && document.querySelector('#giris-tekrar').disabled`));
  await snap('01b-code');
  await js(`document.querySelector('#giris-kod').value='000000';document.querySelector('#giris-kod-form').requestSubmit()`);
  await wait(()=>account.status().errorCode==='wrong_code');
  check('wrong code keeps product locked without data requests',await js(`document.querySelector('#app-main').inert`) && !receipt.requests?.length);
  await js(`document.querySelector('#giris-kod').value='123456';document.querySelector('#giris-kod-form').requestSubmit()`);
  await wait(()=>js(`document.querySelector('#akis-liste').textContent.includes('Sentetik QA haberi')`));
  await js(`for(const d of document.querySelectorAll('dialog[open]')) d.close();document.querySelector('[data-gorunum="akis"]').click()`);
  check('native OTP login unlocks real feed and clears code',await js(`!document.body.classList.contains('session-locked') && !document.querySelector('#giris-kod').value`));
  await wait(()=>receipt.requests.includes('/api/rasathane/bulletins') && receipt.requests.includes('/api/rasathane/conversations'));
  check('history loads only after product state is ready',receipt.requests.indexOf('/api/rasathane/state') < receipt.requests.indexOf('/api/rasathane/bulletins') && receipt.requests.indexOf('/api/rasathane/state') < receipt.requests.indexOf('/api/rasathane/conversations'));
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
  await js(`document.querySelector('#bulten-ac').click();document.querySelector('#bulten-form').requestSubmit()`);
  await wait(()=>js(`!document.querySelector('#bulten-sonuc').hidden && document.querySelectorAll('.bulletin-items li').length===2`));
  check('bulletin saves two source-bound items including honest metadata notice',await js(`document.querySelector('#bulten-sonuc').textContent.includes('Başvuru süresi otuz gündür') && document.querySelector('#bulten-sonuc').textContent.includes('özetlenebilecek haber metni bulunmuyor') && document.querySelectorAll('.bulletin-items a').length===2`));
  await wait(()=>js(`!document.querySelector('#bulten-seslendir').disabled`));
  await js(`document.querySelector('#bulten-seslendir').click()`);
  await wait(()=>js(`document.querySelector('#bulten-ses').readyState>=2`),60000);
  check('bulletin real Turkish WAV playable',await js(`document.querySelector('#bulten-ses').duration>0`));
  await snap('02c-bulletin');
  await js(`document.querySelector('[data-gorunum="calisma"]').click();document.querySelector('.workspace-examples button').click()`);
  await wait(()=>js(`document.querySelectorAll('.workspace-button').length===3 && !document.querySelector('.workspace-examples button').disabled`));
  await js(`document.querySelector('.workspace-examples button').click()`);
  await wait(()=>js(`document.querySelector('.workspace-examples').textContent.includes('0 çalışma alanı, 0 not ve 0 konu')`));
  check('example setup persists and repeated run does not duplicate',await js(`document.querySelectorAll('.workspace-button').length===3`));
  await snap('02d-workspaces');
  await js(`document.querySelector('[data-gorunum="konular"]').click();document.querySelector('.topic-results').click()`);
  await wait(()=>js(`document.querySelector('#konu-sonuc-dialog').open`));
  check('topic results explain no completed search without fake news',await js(`document.querySelector('#konu-sonuc-liste').textContent.includes('Henüz tamamlanmış kontrol yok')`));
  await js(`document.querySelector('#konu-sonuc-dialog').close();document.querySelector('#profil-ac').click();document.querySelector('#profil-ayarlar').click()`);
  check('profile opens settings as modal and keeps underlying topic view',await js(`document.querySelector('#gorunum-ayarlar').open && !document.querySelector('#gorunum-konular').classList.contains('gizli') && !document.querySelector('#sekme-ayarlar')`));
  await snap('02e-settings');
  await js(`document.querySelector('#ayar-sekme-arama').click();document.querySelector('#urun-takip-sikligi').value='240';document.querySelector('#urun-ayar-form').requestSubmit()`);
  await wait(()=>js(`document.querySelector('#urun-ayar-sonuc').textContent.includes('Ayarlar kaydedildi')`));
  check('external settings form controls persist correctly',await js(`document.querySelector('#urun-takip-sikligi').value==='240'`));
  await js(`document.querySelector('#ayarlar-kapat').click()`);
  await js(`document.querySelector('[data-gorunum="arastir"]').click();document.querySelector('#arastir-web').checked=false;document.querySelector('#arastir-sorgu').value='Başvuru süresi nedir?';document.querySelector('#arastir-form').requestSubmit()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===1 && !document.querySelector('#arastir-btn').disabled`),20000);
  check('first source-bound chat answer',await js(`document.querySelector('.chat-assistant').textContent.includes('otuz')`));
  await js(`document.querySelector('#arastir-sorgu').value='Başvurular nasıl yapılır?';document.querySelector('#arastir-form').requestSubmit()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===2 && !document.querySelector('#arastir-btn').disabled`),20000);
  check('two conversational turns',await js(`document.querySelectorAll('.chat-user').length===2 && document.querySelectorAll('.chat-assistant').length===2`)); await snap('03-chat');
  check('follow-up finds existing source evidence',await js(`Array.from(document.querySelectorAll('.chat-assistant')).at(-1).textContent.includes('çevrimiçi')`));
  win.reload(); await new Promise(r=>win.webContents.once('did-finish-load',r));
  await wait(()=>js(`document.querySelectorAll('.chat-history-item').length>0`));
  await js(`for(const d of document.querySelectorAll('dialog[open]')) d.close();document.querySelector('[data-gorunum="arastir"]').click();document.querySelector('#arastir-gecmis-ac').click();document.querySelector('.chat-history-item').click()`);
  await wait(()=>js(`document.querySelectorAll('.chat-assistant').length===2`));
  check('conversation survives reload',await js(`document.querySelectorAll('.chat-user').length===2`)); await snap('04-persisted');
  check('history lives in research header instead of nested sidebar',await js(`!!document.querySelector('#gorunum-arastir .research-heading #arastir-gecmis') && !document.querySelector('#gorunum-arastir .chat-sidebar')`));
  await js(`document.querySelector('[data-gorunum="akis"]').click();document.querySelector('#bulten-ac').click();const history=document.querySelector('#bulten-gecmis');history.selectedIndex=1;history.dispatchEvent(new Event('change'))`);
  await wait(()=>js(`!document.querySelector('#bulten-sonuc').hidden`));
  check('saved bulletin survives reload',await js(`document.querySelectorAll('.bulletin-items li').length===2`));
  await js(`document.querySelector('[data-gorunum="arastir"]').click()`);
  await js(`document.querySelector('#arastir-gecmis-ac').click();Array.from(document.querySelectorAll('.chat-history-item')).find(n=>n.textContent.startsWith('Uzun QA geçmişi')).click()`);
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
  check('logout clears bulletin and examples status',await js(`document.querySelector('#bulten-sonuc').hidden && !document.querySelector('#bulten-sonuc').textContent && !document.querySelector('#bulten-ses')?.getAttribute('src')`));
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
  gate?.close();account?.close();fs.writeFileSync(path.join(run,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify({run,ok:receipt.ok,failure:receipt.failure,checks:receipt.checks}));win?.destroy();app.exit(receipt.ok?0:1);
 }
});
