const SKILLS = [
  { id: 'script', label: '故事分镜', skill: 'video-script-storyboard', short: '脚本 → 可执行分镜' },
  { id: 'regulator', label: '资产总控', skill: 'video-asset-regulator', short: '分级、门控与路由' },
  { id: 'character', label: '角色设计', skill: 'video-character-design-director', short: '身份与连续性' },
  { id: 'scene', label: '场景设计', skill: 'video-scene-design-director', short: '空间与灯光锁定' },
  { id: 'prop', label: '道具设计', skill: 'video-prop-design-director', short: '结构、比例与交互' },
  { id: 'fusion', label: '融合生产', skill: 'video-fusion-production-director', short: '关键帧与关系参考' },
  { id: 'director', label: '镜头导演', skill: 'video-shot-director', short: '连续性与剪辑交接' },
  { id: 'audio', label: '声音控制', skill: 'voice-controller', short: '配音、配乐与音频 QA' },
  { id: 'seedance', label: '平台打包', skill: 'seedance-shot-packager', short: 'Seedance 执行包' }
];

const demo = {
  id: crypto.randomUUID(), name: '零号计划 · 雨夜来信', ratio: '9:16', duration: 30, generator: 'Seedance 2.0',
  brief: '雨夜，一个独居女孩收到来自明天的语音消息。她必须在门外脚步停下前做出选择。',
  stage: 1, createdAt: new Date().toISOString(),
  script: '雨水敲打窗户。手机在黑暗中亮起。\n\n一条来自“明天”的语音：不要开门。\n\n女孩抬头，门外的脚步声恰好停住。门把手缓慢转动。她屏住呼吸，把手机切换到录音。',
  assets: [
    {id:'C001',name:'林夏',type:'角色',grade:'A',status:'partial',note:'主角身份锚点；缺 FACE close-up',skill:'character'},
    {id:'S001',name:'雨夜卧室',type:'场景',grade:'A+',status:'ready',note:'主场景；布局与侧光已锁定',skill:'scene'},
    {id:'P001',name:'旧款手机',type:'道具',grade:'A',status:'missing',note:'剧情道具；需要交互与亮屏状态',skill:'prop'},
    {id:'BLEND_001',name:'床边持手机',type:'融合',grade:'A',status:'blocked',note:'等待 C001 与 P001 批准',skill:'fusion'},
    {id:'AUD001',name:'雨声与脚步',type:'音频',grade:'B',status:'ready',note:'连续声桥；门外脚步三拍',skill:'seedance'}
  ],
  shots: [
    {id:'SH001',scene:'S001',duration:4,purpose:'建立雨夜空间',size:'全景',camera:'缓慢推进',action:'雨水沿玻璃滑落，房间只有窗外冷光。',status:'ready'},
    {id:'SH002',scene:'S001',duration:4,purpose:'事件触发',size:'特写',camera:'静止微俯',action:'手机在床边亮起并短促震动。',status:'ready'},
    {id:'SH003',scene:'S001',duration:5,purpose:'人物反应',size:'近景',camera:'轻推',action:'林夏睁眼，目光移向手机，呼吸变浅。',status:'partial'},
    {id:'SH004',scene:'S001',duration:5,purpose:'危险逼近',size:'中近景',camera:'侧向慢移',action:'门外三声脚步停下，她转头看向门。',status:'blocked'},
    {id:'SH005',scene:'S001',duration:5,purpose:'悬念升级',size:'特写',camera:'固定',action:'门把手缓慢下压，金属映出冷光。',status:'missing'},
    {id:'SH006',scene:'S001',duration:5,purpose:'结尾反转',size:'近特写',camera:'极慢推进',action:'她按下录音键，对明天的自己低声开口。',status:'missing'}
  ]
};

let state = loadState();
let activeView = 'overview';
let selectedShot = null;

function loadState(){
  try { const saved = JSON.parse(localStorage.getItem('frameflow-state')); if(saved?.projects?.length){saved.projects.forEach(p=>ensureAudioModel(p));return saved;} } catch(e){}
  ensureAudioModel(demo,true);
  return { projects:[demo], currentId:demo.id, settings:{autosave:true,language:'中文',approval:'严格'} };
}
function save(){ if(state.settings.autosave !== false) localStorage.setItem('frameflow-state',JSON.stringify(state)); const el=document.getElementById('saveState'); if(el){el.textContent='已自动保存';} }
function project(){ return state.projects.find(p=>p.id===state.currentId) || state.projects[0]; }
function esc(v=''){ return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function statusLabel(s){ return ({ready:'已批准',approved:'已批准',partial:'待完善',provisional:'临时',planned:'已规划',missing:'缺失',blocked:'阻塞','pending-consent':'待授权','generated-pending-qa':'待质检','revision-required':'需修订',rejected:'已拒绝'})[s]||s; }
function toast(msg){ const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('show'),2200); }
function stageIndex(p){
  if(!p.shots.length) return 0;
  for(const skill of ['character','scene','prop','fusion']){
    if(p.assets.some(a=>a.skill===skill&&a.status!=='ready')) return SKILLS.findIndex(s=>s.id===skill);
  }
  if(p.shots.some(s=>s.status!=='ready')) return SKILLS.findIndex(s=>s.id==='director');
  if(audioSummary(p).readiness!=='ready') return SKILLS.findIndex(s=>s.id==='audio');
  return SKILLS.findIndex(s=>s.id==='seedance');
}

function init(){
  syncProjectSelect(); bindShell(); render();
}
function syncProjectSelect(){ const sel=document.getElementById('projectSelect');sel.innerHTML=state.projects.map(p=>`<option value="${p.id}" ${p.id===state.currentId?'selected':''}>${esc(p.name)}</option>`).join(''); }
function bindShell(){
  document.getElementById('mainNav').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;activeView=b.dataset.view;document.querySelectorAll('.nav-item[data-view]').forEach(x=>x.classList.toggle('active',x===b));render();});
  document.getElementById('projectSelect').addEventListener('change',e=>{state.currentId=e.target.value;save();render();});
  document.getElementById('newProjectBtn').onclick=()=>document.getElementById('projectDialog').showModal();
  document.getElementById('projectForm').addEventListener('submit',createProject);
  document.getElementById('settingsBtn').onclick=()=>document.getElementById('settingsDialog').showModal();
  document.getElementById('settingsDialog').addEventListener('close',()=>{state.settings.autosave=document.getElementById('autosaveSetting').checked;state.settings.language=document.getElementById('languageSetting').value;state.settings.approval=document.getElementById('approvalSetting').value;save();});
  document.getElementById('exportBtn').onclick=exportProject;
  document.getElementById('quickRunBtn').onclick=runNext;
  document.getElementById('focusBtn').onclick=()=>document.body.classList.toggle('focus');
  document.getElementById('globalSearch').addEventListener('input',e=>search(e.target.value));
}
function createProject(e){
  if(e.submitter?.value==='cancel') return;
  e.preventDefault(); const fd=new FormData(e.currentTarget); const p={id:crypto.randomUUID(),name:fd.get('name'),ratio:fd.get('ratio'),duration:+fd.get('duration'),generator:fd.get('generator'),brief:fd.get('brief'),stage:0,createdAt:new Date().toISOString(),script:'',assets:[],shots:[]};ensureAudioModel(p);
  state.projects.push(p);state.currentId=p.id;save();syncProjectSelect();document.getElementById('projectDialog').close();e.currentTarget.reset();activeView='story';document.querySelectorAll('.nav-item[data-view]').forEach(x=>x.classList.toggle('active',x.dataset.view==='story'));render();toast('项目已创建，先完成故事与分镜');
}
function pageHead(kicker,title,desc,action=''){return `<div class="page-head"><div><p class="eyebrow">${kicker}</p><h1>${esc(title)}</h1><p class="subtle">${desc}</p></div>${action}</div>`}
function pipeline(p){const current=stageIndex(p);return `<div class="panel"><div class="panel-head"><h3>生产流水线</h3><span>点击阶段可生成对应技能任务包</span></div><div class="pipeline">${SKILLS.map((s,i)=>`<article class="pipe-node ${i<current?'done':''} ${i===current?'active':''}" data-skill="${s.id}"><div class="pipe-num">${i<current?'✓':String(i+1).padStart(2,'0')}</div><strong>${s.label}</strong><small>${s.short}</small></article>`).join('')}</div></div>`}
function bindPipeline(){document.querySelectorAll('[data-skill]').forEach(x=>x.onclick=()=>copySkillTask(x.dataset.skill));}
function copySkillTask(skillId){const p=project(),s=SKILLS.find(x=>x.id===skillId);if(!s)return;const characterPolicy=skillId==='character'?'\n人物资产策略：轻量默认。A 级人物默认只要求 DES_master + FACE_neutral + 合并文字规格；表情组、侧背面、服装拆解、细节图和设定板仅按明确镜头依赖追加。\n':'';const audioContext=skillId==='audio'?`\n声音资产摘要：${audioTaskSummary(p)}\n请按 Voice Controller 的授权、执行确认、Take 版本和音频 QA 门禁处理。\n`:'';const task=`使用 $${s.skill} 继续项目「${p.name}」。\n\n项目摘要：${p.brief}\n时长：${p.duration} 秒\n画幅：${p.ratio}\n目标生成器：${p.generator}\n当前资产：${p.assets.map(a=>`${a.id} ${a.name} [${statusLabel(a.status)}]`).join('；')||'暂无'}\n当前镜头：${p.shots.map(x=>`${x.id} ${x.purpose} [${statusLabel(x.status)}]`).join('；')||'暂无'}\n${characterPolicy}${audioContext}\n请保留现有 ID，按该技能的输出契约返回最小可执行下一步。`;navigator.clipboard?.writeText(task);toast(`已复制 ${s.label} 任务包`);}
function render(){ const p=project();ensureAudioModel(p);document.getElementById('assetBadge').textContent=p.assets.filter(a=>a.status!=='ready').length;document.getElementById('audioBadge').textContent=audioSummary(p).openItems; const routes={overview:renderOverview,story:renderStory,assets:renderAssets,shots:renderShots,audio:renderAudio,generate:renderImageStudio,review:renderReview};document.getElementById('content').innerHTML=routes[activeView](p);document.querySelectorAll('.panel-head h3').forEach(h=>{const heading=document.createElement('h2');heading.innerHTML=h.innerHTML;h.replaceWith(heading);});bindView(); }
function renderOverview(p){const ready=p.assets.filter(a=>a.status==='ready').length,total=p.assets.length||1,progress=Math.round((ready/total)*100);return `${pageHead('PRODUCTION OVERVIEW',p.name,'从创意、资产到镜头交付的单一事实源。',`<span class="stage-pill">阶段 ${stageIndex(p)+1}/${SKILLS.length} · ${SKILLS[stageIndex(p)]?.label||'交付'}</span>`)}<section class="stats"><div class="stat"><span>资产就绪率</span><strong>${progress}%</strong><small>${ready}/${p.assets.length} 个资产已批准</small></div><div class="stat" style="--glow:var(--cyan)"><span>镜头计划</span><strong>${p.shots.length}</strong><small>${p.shots.reduce((a,x)=>a+x.duration,0)}s / 目标 ${p.duration}s</small></div><div class="stat" style="--glow:var(--orange)"><span>当前阻塞</span><strong>${p.assets.filter(a=>['blocked','missing'].includes(a.status)).length}</strong><small>优先处理 A 级缺口</small></div><div class="stat" style="--glow:var(--violet)"><span>目标模型</span><strong style="font-size:18px;margin-top:14px">${esc(p.generator)}</strong><small>${p.ratio} · ${p.duration} 秒</small></div></section>${pipeline(p)}<div class="grid" style="margin-top:14px"><section class="panel command"><div class="panel-head"><h3>导演指令</h3><span>自然语言驱动项目</span></div><div class="panel-body"><textarea id="commandInput" placeholder="例如：把开场改得更有悬念，并拆成 6 个适合图生视频的镜头……">${esc(p.brief)}</textarea><div class="command-actions"><div class="chips"><button class="chip" data-template="优化故事钩子">故事钩子</button><button class="chip" data-template="检查所有 A 级资产缺口">资产体检</button><button class="chip" data-template="为下一镜头生成 Seedance 执行包">镜头打包</button></div><button class="primary" id="commandRun">生成任务包 ↗</button></div></div></section><section class="panel"><div class="panel-head"><h3>项目就绪门</h3><span>严格模式</span></div><div class="panel-body"><div class="progress-ring" style="--p:${progress}"><div><strong>${progress}%</strong><span>READY</span></div></div>${[['分镜表',p.shots.length>0],['A 级资产',!p.assets.some(a=>a.grade.startsWith('A')&&a.status!=='ready')],['融合参考',!p.assets.some(a=>a.type==='融合'&&a.status!=='ready')],['镜头导演包',p.stage>=6],['声音交接',audioSummary(p).readiness==='ready']].map(x=>`<div class="gate-row"><span>${x[0]}</span><b style="color:${x[1]?'var(--cyan)':'var(--orange)'}">${x[1]?'通过':'待处理'}</b></div>`).join('')}</div></section><section class="panel"><div class="panel-head"><h3>下一步任务</h3><span>${p.assets.filter(a=>a.status!=='ready').length} 项待处理</span></div><div class="task-list">${p.assets.filter(a=>a.status!=='ready').slice(0,4).map(a=>`<div class="task" data-asset="${a.id}"><i class="task-dot ${a.status==='partial'?'ready':'high'}"></i><div><strong>${a.id} · ${a.name}</strong><small>${a.note}</small></div><b>${statusLabel(a.status)}</b></div>`).join('')||'<div class="empty">所有资产已就绪</div>'}</div></section><section class="panel"><div class="panel-head"><h3>制作原则</h3><span>已锁定</span></div><div class="panel-body"><div class="gate-row"><span>稳定 ID / 版本</span><b>开启</b></div><div class="gate-row"><span>Prompt QA 后生成</span><b>开启</b></div><div class="gate-row"><span>声音授权后克隆</span><b>开启</b></div><div class="gate-row"><span>镜头导演强制门</span><b>开启</b></div></div></section></div>`}
function renderStory(p){return `${pageHead('PRE-PRODUCTION','故事与分镜','把文学描述转成可见、可听、可生成、可剪辑的镜头。',`<button class="primary" id="storyTask">复制分镜技能任务</button>`)}<div class="story-layout"><section class="panel script-box"><div class="panel-head"><h3>可视化脚本</h3><span id="wordCount">${p.script.length} 字</span></div><textarea id="scriptText" placeholder="在这里写下故事或粘贴脚本……">${esc(p.script)}</textarea></section><section class="panel"><div class="panel-head"><h3>分镜板</h3><div class="toolbar"><span>${p.shots.length} 镜头 · ${p.shots.reduce((a,s)=>a+s.duration,0)} 秒</span><button class="mini-button" id="addShotTop">＋ 镜头</button></div></div><div class="storyboard">${p.shots.map((s,i)=>shotCard(s,i)).join('')}<button class="add-shot" id="addShot">＋<br>添加镜头</button></div></section></div>`}
function shotCard(s,i){return `<article class="shot-card ${selectedShot===s.id?'selected':''}" data-shot="${s.id}"><div class="shot-preview" data-id="${s.id}" style="filter:hue-rotate(${i*22}deg)"></div><div class="shot-meta"><strong>${esc(s.purpose)}</strong><p>${esc(s.action)}</p><footer><span>${s.size}</span><span>${s.duration}s · ${statusLabel(s.status)}</span></footer></div></article>`}
function renderAssets(p){return `${pageHead('ASSET CONTROL','资产工坊','角色、场景、道具、融合与音频资产在这里分级、质检和注册。',`<button class="primary" id="assetTask">运行资产体检</button>`)}<div class="panel lean-policy"><div class="panel-head"><h3>人物资产 · 轻量默认</h3><span>不足时后期追加</span></div><div class="lean-policy-grid"><div><b>A 级主角</b><span>DES_master + FACE_neutral + 合并文字规格</span></div><div><b>条件追加</b><span>表情组、侧背面、复杂服装、标志细节、设定板</span></div><div><b>B / C 级</b><span>B 级一张脸服参考；C 级仅保留 Prompt</span></div></div></div><div class="panel" style="margin-bottom:14px"><div class="panel-head"><div class="toolbar"><select id="assetFilter"><option value="all">全部资产</option><option>角色</option><option>场景</option><option>道具</option><option>融合</option><option>音频</option></select><select id="statusFilter"><option value="all">全部状态</option><option value="ready">已批准</option><option value="partial">待完善</option><option value="missing">缺失</option><option value="blocked">阻塞</option></select></div><button class="mini-button" id="addAsset">＋ 登记资产</button></div></div><div class="asset-grid" id="assetGrid">${p.assets.map(assetCard).join('')||'<section class="panel empty">暂无资产，先运行资产总控提取清单。</section>'}</div>`}
function assetCard(a){const cls=a.type==='场景'?'scene':a.type==='道具'?'prop':a.type==='融合'?'fusion':'';return `<article class="asset-card" data-asset="${a.id}" data-type="${a.type}" data-status="${a.status}"><div class="asset-visual ${cls}"><b class="asset-grade">${a.grade} 级</b><span class="asset-type">${a.type}</span></div><div class="asset-info"><strong>${a.id} · ${esc(a.name)}</strong><p>${esc(a.note)}</p><div class="status-line"><span class="status ${a.status}">${statusLabel(a.status)}</span><span>v01 · ${SKILLS.find(s=>s.id===a.skill)?.label||'总控'}</span></div></div></article>`}
function renderShots(p){const s=p.shots.find(x=>x.id===selectedShot)||p.shots[0];selectedShot=s?.id||null;if(!s)return `${pageHead('SHOT DIRECTION','镜头导演','定义摄影、表演、连续性与剪辑交接。')}<section class="panel empty">还没有镜头，请先到“故事与分镜”创建镜头。</section>`;return `${pageHead('SHOT DIRECTION','镜头导演','每个镜头只有一个主要动作和一个情绪转折。',`<button class="primary" id="directorTask">复制镜头导演任务</button>`)}<div class="inspector-grid"><section class="panel"><div class="panel-head"><h3>镜头序列</h3><span>${p.shots.length} SHOTS</span></div><div class="storyboard" style="min-height:260px">${p.shots.map((x,i)=>shotCard(x,i)).join('')}</div></section><aside class="panel"><div class="panel-head"><h3>${s.id} 检查器</h3><span class="status ${s.status}">${statusLabel(s.status)}</span></div><div class="panel-body"><div class="field"><label>镜头目的</label><input data-shot-field="purpose" value="${esc(s.purpose)}"></div><div class="field"><label>可见动作</label><textarea data-shot-field="action">${esc(s.action)}</textarea></div><div class="form-grid"><div class="field"><label>景别</label><input data-shot-field="size" value="${esc(s.size)}"></div><div class="field"><label>时长（秒）</label><input data-shot-field="duration" type="number" min="1" max="15" value="${s.duration}"></div></div><div class="field"><label>摄影机</label><input data-shot-field="camera" value="${esc(s.camera)}"></div><div class="field"><label>Seedance 模式建议</label><select><option>General reference</option><option>First-last frames</option><option>Smart multi-frame</option><option>image-to-video</option></select></div><div class="field"><label>连续性锁</label><textarea>屏幕方向保持左→右；视线落向门；保留 8 帧 pre-roll 与 10 帧 post-roll。</textarea></div></div></aside></div>`}
function renderGenerate(p){return `${pageHead('GENERATION DESK','生成工作台','把批准资产映射为明确角色，并生成可复制的平台执行包。',`<button class="primary" id="seedanceTask">生成 Seedance 任务包</button>`)}<div class="inspector-grid"><section class="panel"><div class="panel-head"><h3>执行参数</h3><span>${esc(p.generator)}</span></div><div class="panel-body"><div class="form-grid"><div class="field"><label>生成模式</label><select><option>General reference</option><option>First-last frames</option><option>Smart multi-frame</option><option>Video extension</option></select></div><div class="field"><label>时长 / 画幅</label><input value="6 秒 · ${p.ratio}" readonly></div></div><div class="field"><label>最终中文 Prompt</label><textarea id="finalPrompt" style="min-height:260px">生成一个 6 秒、${p.ratio} 的连续电影感镜头。保持角色身份、服装、场景布局与侧光方向稳定。主体完成一个清晰动作，镜头运动克制，保留可用的 cut-in 与 cut-out。不要生成字幕、水印、网格、额外人物、错误手指或漂浮物体。</textarea></div><div class="command-actions"><div class="chips"><span class="chip">身份锁</span><span class="chip">场景锁</span><span class="chip">剪辑可用性</span></div><button class="primary" id="copyPrompt">复制 Prompt</button></div></div></section><aside class="panel"><div class="panel-head"><h3>引用角色</h3><span>显式映射</span></div><div class="panel-body">${p.assets.filter(a=>a.status==='ready').map((a,i)=>`<div class="ref-row"><i class="ref-thumb"></i><div><strong>@${a.type==='音频'?'Audio':'Image'}${i+1} · ${a.id}</strong><span>${a.type==='角色'?'控制角色身份与服装':a.type==='场景'?'控制空间布局与光线':a.type==='音频'?'控制环境声与节奏':'控制物体身份与比例'}</span></div><b>✓</b></div>`).join('')||'<div class="empty">暂无已批准引用</div>'}<div class="gate-row"><span>引用数量限制</span><b>通过</b></div><div class="gate-row"><span>A 级引用完整</span><b style="color:var(--orange)">待处理</b></div></div></aside></div>`}
function renderReview(p){const audio=audioSummary(p),audioClips=[...(p.audio.dialogues||[]).map(d=>`${d.id} · ${d.selectedTakeId||'待选 Take'}`),...(p.audio.musicCues||[]).map(c=>`${c.id} · ${c.purpose}`)];return `${pageHead('REVIEW & DELIVERY','质检与交付','镜头不只要好看，还必须能接入序列、能剪、能回退。',`<button class="primary" id="exportReport">导出交付报告</button>`)}<section class="panel"><div class="panel-head"><h3>剪辑时间线</h3><span>${p.ratio} · ${p.shots.reduce((a,s)=>a+s.duration,0)} 秒</span></div><div class="timeline"><div class="track"><b class="track-label">VIDEO</b>${p.shots.map(s=>`<div class="clip video" style="grid-column:span ${Math.max(1,Math.round(s.duration/2))}">${s.id}</div>`).join('')}</div><div class="track"><b class="track-label">AUDIO</b><div class="clip audio" style="grid-column:span 12">${esc(audioClips.join(' · ')||'暂无已登记声音')}</div></div><div class="track"><b class="track-label">TEXT</b><div class="clip text" style="grid-column:6/span 4">后期字幕 / UI</div></div></div></section><div class="stats" style="margin-top:14px"><div class="stat"><span>可用镜头</span><strong>${p.shots.filter(s=>s.status==='ready').length}</strong><small>通过生成视频 QA</small></div><div class="stat"><span>需重试</span><strong>${p.shots.filter(s=>s.status==='partial').length}</strong><small>窄问题可继续修订</small></div><div class="stat"><span>声音就绪</span><strong>${audio.approved}/${audio.total}</strong><small>${audio.blocked} 项受授权或 QA 阻塞</small></div><div class="stat"><span>交付状态</span><strong style="font-size:18px">${audio.readiness==='ready'&&!p.shots.some(s=>s.status!=='ready')?'可交付':'制作中'}</strong><small>完成视频与声音 QA 后导出</small></div></div>`}
function bindView(){
  bindPipeline();
  bindImageStudio();
  bindAudioView();
  document.querySelectorAll('[data-template]').forEach(b=>b.onclick=()=>{document.getElementById('commandInput').value=b.dataset.template;});
  document.getElementById('commandRun')?.addEventListener('click',()=>{project().brief=document.getElementById('commandInput').value;save();copySkillTask(SKILLS[stageIndex(project())]?.id||'script');});
  document.getElementById('storyTask')?.addEventListener('click',()=>copySkillTask('script'));
  document.getElementById('assetTask')?.addEventListener('click',()=>copySkillTask('regulator'));
  document.getElementById('directorTask')?.addEventListener('click',()=>copySkillTask('director'));
  document.getElementById('seedanceTask')?.addEventListener('click',()=>copySkillTask('seedance'));
  document.getElementById('copyPrompt')?.addEventListener('click',()=>{navigator.clipboard?.writeText(document.getElementById('finalPrompt').value);toast('Prompt 已复制');});
  document.getElementById('scriptText')?.addEventListener('input',e=>{project().script=e.target.value;document.getElementById('wordCount').textContent=e.target.value.length+' 字';save();});
  document.getElementById('addShot')?.addEventListener('click',addShot);document.getElementById('addShotTop')?.addEventListener('click',addShot);
  document.querySelectorAll('[data-shot]').forEach(c=>c.onclick=()=>{selectedShot=c.dataset.shot;if(activeView!=='shots'){activeView='shots';document.querySelectorAll('.nav-item[data-view]').forEach(x=>x.classList.toggle('active',x.dataset.view==='shots'));}render();});
  document.querySelectorAll('[data-shot-field]').forEach(el=>el.addEventListener('change',e=>{const s=project().shots.find(x=>x.id===selectedShot);s[e.target.dataset.shotField]=e.target.type==='number'?+e.target.value:e.target.value;save();render();}));
  document.getElementById('assetFilter')?.addEventListener('change',filterAssets);document.getElementById('statusFilter')?.addEventListener('change',filterAssets);
  document.querySelectorAll('[data-asset]').forEach(el=>el.onclick=()=>{const a=project().assets.find(x=>x.id===el.dataset.asset);if(a)copySkillTask(a.skill);});
  document.getElementById('addAsset')?.addEventListener('click',()=>toast('请先运行资产总控，由总控登记稳定 ID'));
  document.getElementById('exportReport')?.addEventListener('click',exportReport);
}
function addShot(){const p=project(),n=p.shots.length+1;p.shots.push({id:`SH${String(n).padStart(3,'0')}`,scene:'S001',duration:4,purpose:'新镜头',size:'中景',camera:'固定',action:'描述一个可见动作。',status:'missing'});save();render();toast('镜头已添加');}
function filterAssets(){const t=document.getElementById('assetFilter').value,s=document.getElementById('statusFilter').value;document.querySelectorAll('.asset-card').forEach(c=>c.style.display=(t==='all'||c.dataset.type===t)&&(s==='all'||c.dataset.status===s)?'block':'none');}
function runNext(){copySkillTask(SKILLS[stageIndex(project())]?.id||'script');}
function search(q){q=q.trim().toLowerCase();if(!q)return;const p=project(),shot=p.shots.find(s=>Object.values(s).join(' ').toLowerCase().includes(q)),asset=p.assets.find(a=>Object.values(a).join(' ').toLowerCase().includes(q));if(shot){selectedShot=shot.id;activeView='shots';render();toast(`已定位 ${shot.id}`);}else if(asset){activeView='assets';render();setTimeout(()=>document.querySelector(`[data-asset="${asset.id}"]`)?.scrollIntoView({behavior:'smooth',block:'center'}),0);toast(`已定位 ${asset.id}`);}}
function download(name,text,type='application/json'){const blob=new Blob([text],{type:`${type};charset=utf-8`}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href);}
function exportProject(){const p=project();download(`${p.name.replace(/[\\/:*?"<>|]/g,'_')}.frameflow.json`,JSON.stringify(p,null,2));toast('项目 JSON 已导出');}
function exportReport(){const p=project();const md=`# ${p.name}｜交付报告\n\n- 画幅：${p.ratio}\n- 目标时长：${p.duration} 秒\n- 生成器：${p.generator}\n\n## 项目摘要\n\n${p.brief}\n\n## 资产状态\n\n${p.assets.map(a=>`- ${a.id} ${a.name}｜${a.grade}｜${statusLabel(a.status)}`).join('\n')}\n\n## 镜头状态\n\n${p.shots.map(s=>`- ${s.id} ${s.duration}s｜${s.purpose}｜${statusLabel(s.status)}\n  - ${s.action}`).join('\n')}\n\n## 声音状态\n\n${audioMarkdown(p)}\n`;download(`${p.name}-交付报告.md`,md,'text/markdown');toast('交付报告已导出');}

function imageSizeForRatio(ratio){
  if(['9:16','4:3'].includes(ratio)) return '1024x1536';
  if(ratio==='16:9') return '1536x1024';
  return '1024x1024';
}

function defaultImagePrompt(p){
  const shot=p.shots.find(x=>x.id===selectedShot)||p.shots[0];
  const ready=p.assets.filter(a=>a.status==='ready'&&a.type!=='音频').map(a=>`${a.id} ${a.name}：${a.note}`).join('；');
  return [
    `为 AI 视频项目《${p.name}》制作一张可用于图生视频的电影感关键帧。`,
    shot?`镜头 ${shot.id}（${shot.size}）：${shot.action} 摄影机：${shot.camera}。`:`故事：${p.brief}`,
    ready?`已批准的连续性资产：${ready}。`:'保持人物、场景与关键道具清晰一致。',
    `画幅 ${p.ratio}。构图明确，单一主要动作，光线方向稳定，预留运动空间。`,
    '不要字幕、文字、水印、拼图、分镜网格、额外人物、漂浮物体或畸形手指。'
  ].join('\n');
}

function renderImageStudio(p){
  const generations=p.generations||[];
  const prompt=p.imagePrompt||defaultImagePrompt(p);
  const cards=generations.slice().reverse().map(item=>`<article class="generation-card"><img src="${esc(item.url)}" alt="${esc(item.shotId||'生成关键帧')}" loading="lazy"><div><strong>${esc(item.shotId||'关键帧')} · ${esc(item.model)}</strong><small>${esc(item.size)} · ${esc(item.quality)} · ${new Date(item.createdAt).toLocaleString('zh-CN')}</small><a href="${esc(item.url)}" download>下载 PNG</a></div></article>`).join('');
  return `${pageHead('OPENAI IMAGE DESK','OpenAI 图片生成','为镜头生成关键帧并自动登记到当前项目。',`<span class="stage-pill">gpt-image-2 · 本地安全代理</span>`)}<div class="image-studio"><section class="panel"><div class="panel-head"><h3>生成参数</h3><span>API 密钥仅由本地服务读取</span></div><div class="panel-body"><div class="form-grid"><div class="field"><label>关联镜头</label><select id="imageShot">${p.shots.map(s=>`<option value="${s.id}" ${s.id===selectedShot?'selected':''}>${s.id} · ${esc(s.purpose)}</option>`).join('')||'<option value="">项目概念图</option>'}</select></div><div class="field"><label>尺寸</label><select id="imageSize"><option value="1024x1024">1024 × 1024</option><option value="1024x1536" ${imageSizeForRatio(p.ratio)==='1024x1536'?'selected':''}>1024 × 1536</option><option value="1536x1024" ${imageSizeForRatio(p.ratio)==='1536x1024'?'selected':''}>1536 × 1024</option></select></div></div><div class="field"><label>质量</label><select id="imageQuality"><option value="low">Low · 草图</option><option value="medium" selected>Medium · 审核</option><option value="high">High · 定稿</option></select></div><div class="field"><label>图片 Prompt</label><textarea id="imagePrompt" class="image-prompt">${esc(prompt)}</textarea></div><div class="generation-actions"><button class="ghost" id="resetImagePrompt">按镜头重建 Prompt</button><button class="primary" id="generateImage">✦ 生成关键帧</button></div><p class="generation-status" id="generationStatus">生成会产生 API 费用；提交前请确认 Prompt、尺寸与质量。</p></div></section><aside class="panel"><div class="panel-head"><h3>生成记录</h3><span>${generations.length} 张</span></div><div class="generation-gallery">${cards||'<div class="empty">还没有生成图片。完成 Prompt QA 后开始第一张关键帧。</div>'}</div></aside></div>`;
}

async function generateOpenAIImage(){
  const button=document.getElementById('generateImage');
  const status=document.getElementById('generationStatus');
  const p=project();
  const prompt=document.getElementById('imagePrompt').value.trim();
  if(!prompt){toast('请先填写图片 Prompt');return;}
  p.imagePrompt=prompt;save();
  button.disabled=true;button.textContent='生成中…';status.textContent='正在请求 gpt-image-2，通常需要几十秒。请不要关闭页面。';
  try{
    const response=await fetch('/api/images/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,size:document.getElementById('imageSize').value,quality:document.getElementById('imageQuality').value})});
    const result=await response.json().catch(()=>({error:'本地服务返回了无法解析的响应。'}));
    if(!response.ok) throw new Error(result.error||`生成失败（${response.status}）`);
    p.generations=p.generations||[];
    p.generations.push({...result,shotId:document.getElementById('imageShot').value||null,prompt,createdAt:new Date().toISOString()});
    save();render();toast('关键帧已生成并登记');
  }catch(error){
    button.disabled=false;button.textContent='✦ 生成关键帧';status.textContent=error.message;status.classList.add('error');toast('图片生成失败');
  }
}

function bindImageStudio(){
  document.getElementById('generateImage')?.addEventListener('click',generateOpenAIImage);
  document.getElementById('imagePrompt')?.addEventListener('change',e=>{project().imagePrompt=e.target.value;save();});
  document.getElementById('imageShot')?.addEventListener('change',e=>{selectedShot=e.target.value||null;project().imagePrompt=defaultImagePrompt(project());save();render();});
  document.getElementById('resetImagePrompt')?.addEventListener('click',()=>{project().imagePrompt=defaultImagePrompt(project());save();render();toast('已按当前镜头重建 Prompt');});
}

init();
