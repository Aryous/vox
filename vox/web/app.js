/* vox WebUI：音色库 / 试音台 / 转写 / 模型 / API。只调用 vox 的原生 API（/api/*），与 CLI 共用同一套模型、音色、参数。
   模型分两类（task）：tts 语音合成（音色库、试音台）、stt 语音识别（转写）。 */
(() => {
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ORIGIN = location.origin;
const GEN_DEFAULT = { temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05 };
const LANGS = ['chinese', 'english', 'japanese', 'korean', 'german', 'french', 'russian', 'portuguese', 'spanish', 'italian', 'auto'];
const STATUS = { loaded: '已加载', ready: '可用', not_downloaded: '未下载', downloading: '下载中', needs_key: '未连接' };
const QUICK = ['你好呀，今天过得怎么样？', '我……没问一声，就把 Docker 镜像删了。', '老规矩：先查清，再说明，等你拍板。', 'The quick brown fox jumps over the lazy dog.'];

const store = {
  get(k, d) { try { const v = localStorage.getItem('vox2.' + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('vox2.' + k, JSON.stringify(v)); } catch {} },
};
const S = {
  models: [], voices: [], providers: [], status: null, cat: { instructions: [], design: [] }, settings: { sample_text: '', favorites: [] }, hist: [], clones: [], cn: { file: null, url: null, rec: null },
  // 音色库筛选：kind = 全部 / 预置 / 预设 / 克隆；model = 某个模型或某家 Provider（p:<id>），只筛预置音色。旧版把两者混在 model 里（my = 预设）
  vf: (f => { const k = { my: 'preset', preset: 'preset', clone: 'clone' }[f.model]; return { q: '', gender: '', lang: '', fav: false, ...f, kind: f.kind || k || 'all', model: k || ['all', 'ready'].includes(f.model) ? '' : f.model || '' }; })(store.get('vf', {})), vlimit: 60,
  slots: store.get('slots', null), text: store.get('text', QUICK[0]), exAll: false,
  equiv: store.get('equiv', 'cli'), apiTab: 'curl', autoAsr: store.get('autoAsr', true),
};

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(typeof j.error === 'string' ? j.error : j.error?.message || `HTTP ${r.status}`);
  return j;
}
/* 合成：克隆音色第一次用在会收费的云端时，服务端先拒绝并说明费用；用户确认后带上 accept_fee 重发 */
async function speech(body) {
  try { return await api('/api/speech', body); }
  catch (e) {
    if (!/accept_fee/.test(e.message) || !confirm(e.message.split('确认后重试')[0] + '\n\n确认上传并继续？')) throw e;
    return api('/api/speech', { ...body, accept_fee: true });
  }
}
/* 文本输入：中文输入法组字期间（拼音还没上屏）不触发，确认上屏后再处理；否则重绘会打断组字，把拼音当英文留下 */
function onText(inp, fn, delay = 0) {
  if (!inp || inp._onText) return; inp._onText = true;
  let t; const run = () => { clearTimeout(t); t = setTimeout(fn, delay); };
  inp.addEventListener('input', e => { if (!e.isComposing) run(); });
  inp.addEventListener('compositionend', run);
}
function toast(msg, ms = 2400) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), ms); }
async function copy(text, what = '已复制') { try { await navigator.clipboard.writeText(text); toast(what); } catch { toast('复制失败，请手动选择'); } }

/* ---------- 图标：线性 SVG，一套笔画（24 视框，1.8 描边） ---------- */
const IC = {
  play: '<path d="M8 5.2v13.6a.6.6 0 0 0 .92.5l10.2-6.8a.6.6 0 0 0 0-1L8.92 4.7A.6.6 0 0 0 8 5.2z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6.5" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="13.9" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/>',
  star: '<path d="M12 3.6l2.55 5.17 5.7.83-4.13 4.02.98 5.68L12 16.62 6.9 19.3l.98-5.68L3.75 9.6l5.7-.83z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  ext: '<path d="M14 5h5v5M19 5l-8 8M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 19h14"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  wave: '<path d="M3 12h1.5M7 8v8M11 4v16M15 7.5v9M19 10.5v3M21.5 12H21"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  box: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  code: '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5"/>',
  layers: '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.5L12 17l8.5-4.5M3.5 16.5L12 21l8.5-4.5"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l2.5 2.5M14 9l2 2"/>',
  edit: '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M14.5 7.5l3 3"/>',
  upload: '<path d="M12 16V5M7 10l5-5 5 5M5 19h14"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  dup: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5M14 11.5v5M11.5 14h5"/>',
  more: '<circle cx="5.5" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
  dice: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="15" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/><circle cx="9" cy="15" r="1" fill="currentColor"/>',
};
const ic = (n, size = 16, cls = '') => `<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n]}</svg>`;

/* ---------- 模型工具 ---------- */
const M = id => id ? S.models.find(m => m.id === id || m.alias === id) : undefined;
const short = m => m?.alias || m?.id;
const hue = id => { const m = M(id); return m?.provider === 'local' ? `var(--${m.engine || 'cloud'}, var(--cloud))` : `var(--p-${m?.provider || 'cloud'}, var(--cloud))`; };
const PV = id => S.providers.find(p => p.id === id);
const MONO = new Set(['openai', 'elevenlabs', 'xiaomimimo', 'openrouter']);
const ICON = { local: 'huggingface', openrouter: 'openrouter', openai: 'openai', inworld: null, elevenlabs: 'elevenlabs', gemini: 'gemini', aliyun: 'bailian', volcengine: 'doubao', minimax: 'minimax', stepfun: 'stepfun', siliconflow: 'siliconcloud', mimo: 'xiaomimimo' };
const LETTER_ICON = { inworld: 'In' };
/* Provider 图标：LobeHub Icons（MIT）。单色图标用 CSS mask 跟随主题颜色；缺图标的用字母标。 */
function pIcon(pid, size = 16) {
  const f = ICON[pid];
  if (!f) return `<span class="pic letter" style="--s:${size}px" aria-hidden="true">${esc(LETTER_ICON[pid] || PV(pid)?.letter || pid.slice(0, 2))}</span>`;
  return MONO.has(f) ? `<span class="pic mono" style="--s:${size}px;--src:url(icons/${f}.svg)" aria-hidden="true"></span>` : `<img class="pic" src="icons/${f}.svg" width="${size}" height="${size}" alt="" aria-hidden="true">`;
}
const usable = m => m && ['ready', 'loaded'].includes(m.status);
const mine = () => S.models.filter(m => m.mine);
const isTTS = m => m.task !== 'stt';
const mineTTS = () => mine().filter(isTTS);
// 音色 ID 的显示名只取预置音色：「预设」也挂在同一个 model + voice 上，但名字里带着语气等附加信息
const voiceName = (model, voice) => typeof voice === 'string' && voice.startsWith('clone:') ? S.clones.find(c => 'clone:' + c.id === voice)?.name || voice
  : S.voices.find(v => v.model === model && v.voice === voice && v.kind === 'builtin')?.name || voice;

/* ---------- 模型名字：主名 + 次要信息 + 标签（不在名字里用括号标注） ---------- */
// 「OmniVoice（克隆）」→ 主名 OmniVoice + 标签「克隆」；「Qwen3-TTS CustomVoice 1.7B · 8bit」→ 主名 + 次要信息 8bit
const mParts = m => { const raw = String(m?.name || m?.id || '').replace(/\s*[（(][^（）()]*[）)]\s*$/, '').trim(); const [name, ...q] = raw.split(' · '); return { name, quant: q.join(' · ') }; };
const mName = m => mParts(m).name;
const STATUS_TAG = { loaded: ['已加载', 'ok'], not_downloaded: ['未下载', 'warn'], downloading: ['下载中', 'warn'], needs_key: ['未连接', 'warn'] };
// 模型标签：能力类（克隆、声音设计、识别）+ 状态类（已加载、未下载、未连接）+ 收费
function mTags(m, { status = true, caps = true } = {}) {
  const t = [];
  if (caps && m.caps?.clone) t.push(['克隆', 'clone']);
  if (caps && m.caps?.design) t.push(['声音设计', 'design']);
  if (status && STATUS_TAG[m.status] && m.status !== 'ready') t.push(STATUS_TAG[m.status]);
  if (m.clone?.fee) t.push(['收费', 'mute']);
  return t;
}
const tagHtml = ([t, k]) => `<span class="t t-${k || 'mute'}">${esc(t)}</span>`;
const mIcon = (m, size = 14) => m.provider === 'local' ? `<i class="dot" style="--m:${hue(m.id)}"></i>` : pIcon(m.provider, size);
const mTitle = m => { const p = mParts(m); return `<span class="mn">${esc(p.name)}</span>${p.quant ? `<span class="mq">${esc(p.quant)}</span>` : ''}`; };
const pvName = pid => pid === 'local' ? '本地' : PV(pid)?.name || pid;
// 下拉框里的模型选项：按 Provider 分组，本地在前
function modelGroups(ms, opt = {}) {
  const pids = [...new Set(ms.map(m => m.provider))].sort((a, b) => (a !== 'local') - (b !== 'local'));
  return pids.map(pid => ({ label: pvName(pid), icon: pid === 'local' ? '' : pIcon(pid, 13), items: ms.filter(m => m.provider === pid).map(m => ({ value: m.id, html: mTitle(m), icon: mIcon(m), tags: mTags(m, opt), text: `${m.name} ${m.id}` })) }));
}

// 模型能力：只列支持的；模型页和转写共用一种写法
const CAP_T = m => isTTS(m) ? [['voices', '预置音色'], ['clone', '声音克隆'], ['instructions', m.instr_enum ? '情绪枚举' : '情绪指令'], ['design', '声音设计'], ['seed', '可复现']]
  : [['segments', '分句时间戳'], ['words', '逐词时间戳'], ['diarize', '区分说话人'], ['hotwords', '热词'], ['prompt', '上下文提示']];
const capsHtml = m => { const t = CAP_T(m).filter(([k]) => m.caps[k]); return t.length ? `<div class="caps">${t.map(([, x]) => `<span>${ic('check', 12)}${x}</span>`).join('')}</div>` : ''; };

/* ---------- 下拉选择：替代系统 select ----------
   dd(id, {value, groups:[{label, icon, items:[{value, label|html, sub, icon, tags, text, disabled}]}], onChange, placeholder, search, menu, trigger})
   选项是「主名 + 次要信息 + 标签」三层；超过 8 项自动带搜索；menu = 动作菜单（不显示当前值）。 */
const DD = {};
const ICV = '<svg class="ic dd-cv" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg>';
const ddItems = o => o.groups.flatMap(g => g.items);
const ddLabel = it => `${it.icon || ''}<span class="dd-l">${it.html || esc(it.label)}</span>`;
function dd(id, o) {
  DD[id] = o;
  if (o.menu) return `<button type="button" class="${o.cls || 'btn ghost icon'}" data-dd="${id}" aria-haspopup="menu" aria-expanded="false" ${o.title ? `title="${esc(o.title)}" aria-label="${esc(o.title)}"` : ''}>${o.trigger}</button>`;
  const cur = ddItems(o).find(it => it.value === o.value);
  return `<button type="button" class="dd ${o.cls || ''}" data-dd="${id}" aria-haspopup="listbox" aria-expanded="false" ${o.label ? `aria-label="${esc(o.label)}"` : ''} ${o.disabled ? 'disabled' : ''}>
    ${cur ? `${ddLabel(cur)}${(cur.tags || []).filter(t => o.btnTags !== false && (o.btnTags || ['warn', 'clone', 'design']).includes(t[1])).map(tagHtml).join('')}` : `<span class="dd-ph">${esc(o.placeholder || '选择…')}</span>`}${ICV}</button>`;
}
const POP = Object.assign(document.createElement('div'), { className: 'dd-pop', hidden: true });
POP.setAttribute('role', 'listbox'); document.body.appendChild(POP);
let ddOpen = null;   // {id, btn, q, act}
function ddRender() {
  const { id, q } = ddOpen, o = DD[id], ql = q.trim().toLowerCase();
  const groups = o.groups.map(g => ({ ...g, items: g.items.filter(it => !ql || `${it.label || ''} ${it.text || ''} ${it.sub || ''} ${(it.tags || []).map(t => t[0]).join(' ')}`.toLowerCase().includes(ql)) })).filter(g => g.items.length);
  const flat = groups.flatMap(g => g.items).filter(it => !it.disabled);
  ddOpen.flat = flat; if (ddOpen.act >= flat.length) ddOpen.act = flat.length - 1;
  const search = o.search ?? ddItems(o).length > 8;
  const list = groups.map(g => `${g.label ? `<div class="dd-g">${g.icon || ''}${esc(g.label)}</div>` : ''}${g.items.map(it => {
    const i = flat.indexOf(it), on = !o.menu && it.value === o.value;
    return `<div class="dd-i ${on ? 'on' : ''} ${i === ddOpen.act ? 'act' : ''} ${it.disabled ? 'dis' : ''} ${it.danger ? 'danger' : ''}" role="${o.menu ? 'menuitem' : 'option'}" aria-selected="${on}" data-i="${i}">
      ${it.icon || ''}<div class="dd-t"><div class="dd-r"><span class="dd-l">${it.html || esc(it.label)}</span>${(it.tags || []).map(tagHtml).join('')}</div>${it.sub ? `<div class="dd-s">${esc(it.sub)}</div>` : ''}</div>${on ? ic('check', 14, 'dd-ck') : ''}</div>`;
  }).join('')}`).join('');
  const hadSearch = $('.dd-q', POP), pos = hadSearch?.selectionStart;
  if (hadSearch && search) { $('.dd-list', POP).innerHTML = list || '<div class="dd-empty">没有匹配的选项</div>'; }
  else POP.innerHTML = `${search ? `<div class="dd-sw">${ic('search', 14)}<input class="dd-q" placeholder="搜索" value="${esc(q)}" aria-label="搜索选项"></div>` : ''}<div class="dd-list">${list || '<div class="dd-empty">没有匹配的选项</div>'}</div>`;
  POP.classList.toggle('menu', !!o.menu);
  const qi = $('.dd-q', POP); if (qi && !hadSearch) { qi.focus(); } else if (qi && pos != null) qi.setSelectionRange(pos, pos);
  $('.dd-i.act', POP)?.scrollIntoView({ block: 'nearest' });
}
function ddPlace() {
  if (!ddOpen) return;
  if (!ddOpen.btn.isConnected) return ddClose();
  const r = ddOpen.btn.getBoundingClientRect(), o = DD[ddOpen.id], w = Math.max(r.width, o.width || (o.menu ? 200 : 260));
  POP.style.width = w + 'px'; POP.style.maxHeight = '';
  const left = Math.min(Math.max(8, o.menu ? r.right - w : r.left), innerWidth - w - 8), below = innerHeight - r.bottom - 12, above = r.top - 12;
  const h = Math.min(POP.scrollHeight, 380), up = below < Math.min(h, 240) && above > below;
  POP.style.left = left + 'px'; POP.style.top = up ? '' : r.bottom + 6 + 'px'; POP.style.bottom = up ? innerHeight - r.top + 6 + 'px' : '';
  POP.style.maxHeight = Math.min(380, up ? above : below) + 'px';
}
function ddShow(btn) {
  const id = btn.dataset.dd, o = DD[id]; if (!o) return;
  if (ddOpen?.id === id) return ddClose();
  ddClose(true);
  const host = btn.closest('dialog') || document.body; if (POP.parentNode !== host) host.appendChild(POP);
  const flat = ddItems(o).filter(it => !it.disabled);
  ddOpen = { id, btn, q: '', act: o.menu ? 0 : Math.max(0, flat.findIndex(it => it.value === o.value)) };
  btn.setAttribute('aria-expanded', 'true'); btn.classList.add('open');
  POP.hidden = false; POP.innerHTML = ''; ddRender(); ddPlace();
  if (!$('.dd-q', POP)) POP.focus();
}
function ddClose(silent) {
  if (!ddOpen) return;
  const b = ddOpen.btn; b.setAttribute('aria-expanded', 'false'); b.classList.remove('open');
  POP.hidden = true; POP.innerHTML = ''; ddOpen = null;
  if (!silent && b.isConnected) b.focus({ preventScroll: true });
}
function ddPick(i) {
  const { id, flat } = ddOpen, it = flat[i], o = DD[id]; if (!it) return;
  ddClose(); if (o.menu || it.value !== o.value) o.onChange?.(it.value, it);
}
POP.tabIndex = -1;
POP.addEventListener('mousedown', e => { if (!e.target.closest('.dd-q')) e.preventDefault(); });
POP.addEventListener('click', e => { const it = e.target.closest('.dd-i'); if (it && !it.classList.contains('dis')) ddPick(+it.dataset.i); });
POP.addEventListener('mousemove', e => { const it = e.target.closest('.dd-i:not(.dis)'); if (it && ddOpen && +it.dataset.i !== ddOpen.act) { ddOpen.act = +it.dataset.i; $$('.dd-i', POP).forEach(x => x.classList.toggle('act', x === it)); } });
POP.addEventListener('input', e => { if (e.target.classList.contains('dd-q') && !e.isComposing) { ddOpen.q = e.target.value; ddOpen.act = 0; ddRender(); } });
POP.addEventListener('compositionend', e => { if (e.target.classList.contains('dd-q')) { ddOpen.q = e.target.value; ddOpen.act = 0; ddRender(); } });
document.addEventListener('click', e => {
  const b = e.target.closest('[data-dd]');
  if (b) { e.preventDefault(); return ddShow(b); }
  if (ddOpen && !POP.contains(e.target)) ddClose(true);
});
document.addEventListener('keydown', e => {
  if (!ddOpen) { const b = e.target.closest?.('.dd[data-dd]'); if (b && ['ArrowDown', 'ArrowUp'].includes(e.key)) { e.preventDefault(); ddShow(b); } return; }
  if (e.isComposing) return;
  const n = ddOpen.flat.length;
  if (e.key === 'Escape') { e.preventDefault(); ddClose(); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); ddOpen.act = (ddOpen.act + (e.key === 'ArrowDown' ? 1 : -1) + n) % Math.max(n, 1); ddRender(); }
  else if (e.key === 'Enter') { e.preventDefault(); ddPick(ddOpen.act); }
  else if (e.key === 'Tab') ddClose(true);
}, true);
addEventListener('resize', ddPlace);
addEventListener('scroll', e => { if (ddOpen && !POP.contains(e.target)) ddPlace(); }, true);

/* ---------- 全局播放器 ---------- */
const P = { a: new Audio(), url: null, meta: null };
const peaksCache = {};
let actx;
async function peaks(url) {
  if (peaksCache[url]) return peaksCache[url];
  actx = actx || new (window.AudioContext || window.webkitAudioContext)();
  const buf = await (await fetch(url)).arrayBuffer(), au = await actx.decodeAudioData(buf), d = au.getChannelData(0), n = 300, step = Math.max(1, Math.floor(d.length / n)), out = [];
  for (let i = 0; i < n; i++) { let m = 0; for (let j = i * step; j < (i + 1) * step && j < d.length; j++) m = Math.max(m, Math.abs(d[j])); out.push(m); }
  const mx = Math.max(...out, 0.01);
  return peaksCache[url] = out.map(v => v / mx);
}
async function drawWave(cv, url, prog = 0, color) {
  const pk = await peaks(url).catch(() => null); if (!pk || !cv.isConnected) return;
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight; if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr; const g = cv.getContext('2d'); g.scale(dpr, dpr);
  const cs = getComputedStyle(cv), on = color || cs.getPropertyValue('--m').trim() || '#888', off = getComputedStyle(document.documentElement).getPropertyValue('--line-2').trim();
  const bars = Math.max(10, Math.floor(w / 3));
  for (let i = 0; i < bars; i++) { const v = pk[Math.floor(i / bars * pk.length)], bh = Math.max(1.5, v * (h - 2)); g.fillStyle = i / bars < prog ? on : off; g.fillRect(i * 3, (h - bh) / 2, 2, bh); }
}
function play(url, meta, at) {
  if (P.url === url && at == null) { P.a.paused ? P.a.play() : P.a.pause(); return; }
  if (P.url !== url) { P.a.src = url; P.url = url; P.meta = meta; }
  const bar = $('#player'); bar.hidden = false; bar.style.setProperty('--m', meta.color || 'var(--ink)');
  $('#pTitle').textContent = meta.title; $('#pSub').textContent = meta.sub || '';
  const go = () => { if (at != null && P.a.duration) P.a.currentTime = at * P.a.duration; P.a.play().catch(() => {}); };
  P.a.readyState >= 1 ? go() : (P.a.onloadedmetadata = go);
}
function setPlayIcon(b, playing) { const st = playing ? 'pause' : 'play'; if (b.dataset.st !== st) { b.dataset.st = st; b.innerHTML = ic(st, b.classList.contains('p-play') ? 16 : 14); } }
const fmtT = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
(function loop() {
  const prog = P.a.duration ? P.a.currentTime / P.a.duration : 0, playing = !P.a.paused;
  if (P.url) {
    setPlayIcon($('#pPlay'), playing);
    $('#pTime').textContent = `${fmtT(P.a.currentTime || 0)} / ${fmtT(P.a.duration || 0)}`;
    drawWave($('#pWave'), P.url, prog, P.meta?.color && getComputedStyle($('#player')).getPropertyValue('--m'));
    $$('canvas[data-url]').forEach(cv => { if (cv.dataset.url === P.url || cv._p) { drawWave(cv, cv.dataset.url, cv.dataset.url === P.url ? prog : 0); cv._p = cv.dataset.url === P.url; } });
  }
  $$('.pb[data-url]').forEach(b => { if (!b.classList.contains('busy')) setPlayIcon(b, b.dataset.url === P.url && playing); });
  $$('.vc').forEach(c => c.classList.toggle('playing', !!P.url && c.dataset.url === P.url && playing));
  setTimeout(loop, playing ? 50 : 300);
})();
$('#pPlay').onclick = () => P.url && (P.a.paused ? P.a.play() : P.a.pause());
$('#pWave').onclick = e => { const r = e.currentTarget.getBoundingClientRect(); if (P.a.duration) P.a.currentTime = (e.clientX - r.left) / r.width * P.a.duration; };
document.addEventListener('keydown', e => {
  if (e.target.closest?.('input,textarea,select,.dd-pop') || ddOpen) return;
  if (e.key === ' ' && P.url) { e.preventDefault(); P.a.paused ? P.a.play() : P.a.pause(); }
});

/* ---------- 侧栏服务状态 ---------- */
async function refreshStatus() {
  try { S.status = await api('/api/status'); } catch { S.status = null; }
  const s = S.status, el = $('#srv');
  if (!s) { el.innerHTML = '<div class="row"><span><i class="dot"></i> 服务未连接</span></div>'; return; }
  el.innerHTML = `<div class="row"><span><i class="dot live"></i> 运行中</span><span class="mono">${esc(location.host)}</span></div>
    <div class="row"><span>内存</span><span class="mono">${(s.memory_bytes / 1e9).toFixed(2)} GB</span></div>
    <div class="loaded">${s.loaded.length ? s.loaded.map(id => `<div class="lm" style="--m:${hue(id)}"><i class="dot"></i><span class="mono" title="${esc(M(id)?.name || id)}">${esc(short(M(id)) || id)}</span><button type="button" data-unload="${esc(id)}" title="从内存卸载">卸载</button></div>`).join('') : '<span>没有模型在内存中</span>'}</div>`;
  $$('[data-unload]', el).forEach(b => b.onclick = async () => { await api('/api/models/unload', { model: b.dataset.unload }); toast('已卸载'); await refreshModels(); refreshStatus(); rerender(); });
}
async function refreshModels() { S.models = await api('/api/models'); }
async function refreshVoices() { [S.voices, S.clones] = await Promise.all([api('/api/voices'), api('/api/clones')]); }

/* ---------- 路由 ---------- */
const PAGES = { voices: pageVoices, playground: pagePlayground, transcribe: pageTranscribe, models: pageModels, api: pageApi };
function route() {
  let [, r, sub] = location.hash.match(/^#\/(\w+)(?:\/([\w-]+))?/) || [];
  if (r === 'compare') { r = 'playground'; history.replaceState(null, '', '#/playground'); }   // 对比已经并进试音台
  if (r === 'providers') { r = 'models'; history.replaceState(null, '', `#/models${sub ? '/' + sub : ''}`); } // 旧链接
  if (r === 'voices' && ['clone', 'preset', 'builtin'].includes(sub)) { S.vf.kind = sub; store.set('vf', S.vf); history.replaceState(null, '', '#/voices'); }   // #/voices/clone 直达克隆
  S.route = PAGES[r] ? r : 'voices'; S.sub = sub || (S.route === 'models' ? S.sub : null); render();
}
function render() {
  $$('.nav a').forEach(a => a.classList.toggle('on', a.dataset.route === S.route));
  const main = $('#main'); main.innerHTML = '';
  try { PAGES[S.route](main); }
  catch (e) {   // 渲染出错时不留白：把错误摆出来，方便定位
    console.error(e);
    main.innerHTML = `<div class="empty"><b>这个页面出错了</b>${esc(e.message)}<br><span class="note">刷新试试；如果一直出现，把这段错误发给开发者。</span></div>`;
  }
}
window.addEventListener('hashchange', () => { route(); $('#main').focus({ preventScroll: true }); scrollTo(0, 0); });

/* ============ 音色库 ============ */
// 语言代码（en-US、ar-EG……）显示成中文名；已经是中文的（北京话、多语言）原样显示
const LANG_DN = (() => { try { return new Intl.DisplayNames(['zh-CN'], { type: 'language' }); } catch { return null; } })();
const langName = l => { if (!l || !LANG_DN || !/^[a-z]{2,3}(-[A-Za-z0-9]{2,4})?$/.test(l)) return l; try { return LANG_DN.of(l) || l; } catch { return l; } };
const KINDS = [['all', '全部'], ['builtin', '预置'], ['preset', '预设'], ['clone', '克隆']];
const KIND_TIP = { builtin: '模型或厂商自带的音色', preset: '音色 + 语气 + 语速 + 种子的组合，在试音台调好后保存', clone: '从一段录音得到的声音' };
function filteredVoices(skip) {
  const f = S.vf, q = f.q.trim().toLowerCase(), builtin = f.kind === 'all' || f.kind === 'builtin';
  const okModel = v => { if (!f.model || !builtin) return true; const m = M(v.model); return v.kind === 'builtin' && (f.model.startsWith('p:') ? m?.provider === f.model.slice(2) : v.model === f.model); };
  return S.voices.filter(v => (f.kind === 'all' || v.kind === f.kind) && okModel(v)
    && (skip === 'lang' || !builtin || !f.lang || v.lang === f.lang) && (!builtin || !f.gender || v.gender === f.gender) && (!f.fav || S.settings.favorites.includes(v.ref))
    && (!q || `${v.ref} ${v.name} ${v.description} ${v.lang} ${langName(v.lang)}`.toLowerCase().includes(q)));
}
const setVf = (main, patch) => { Object.assign(S.vf, patch); S.vlimit = 60; store.set('vf', S.vf); pageVoices(main); };
function pageVoices(main) {
  const vs = filteredVoices(), f = S.vf, ms = mine().filter(m => m.caps.voices), builtin = f.kind === 'all' || f.kind === 'builtin';
  const local = ms.filter(m => m.provider === 'local'), provs = [...new Set(ms.filter(m => m.provider !== 'local').map(m => m.provider))];
  const n = { all: S.voices.length, builtin: S.voices.filter(v => v.kind === 'builtin').length, preset: S.voices.filter(v => v.kind === 'preset').length, clone: S.clones.length };
  const langs = Object.entries(filteredVoices('lang').reduce((a, v) => (v.lang && v.kind === 'builtin' && (a[v.lang] = (a[v.lang] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1]);
  const cloudOff = S.providers.filter(p => p.kind === 'cloud' && !p.connected).length;
  main.innerHTML = `
    <div class="head"><div><h1>音色库</h1><p>${n.builtin} 个预置音色，来自 ${[local.length ? `${local.length} 个本地模型` : '', ...provs.map(pid => `${esc(pvName(pid))} 的 ${ms.filter(m => m.provider === pid).length} 个模型`)].filter(Boolean).join('、') || '已添加的模型'}。每个音色都读同一段样本文本，方便横向比较。${cloudOff ? `<a href="#/models/mine">添加更多模型</a>` : ''}</p></div>
      <div class="head-a"><button class="cli" type="button" data-copy="vox voices --json">vox voices --json</button><button class="btn primary" type="button" id="toClone">${ic('mic', 15)}克隆声音</button></div></div>
    <div class="vbar">
      <div class="tabs" role="tablist" aria-label="音色类型">${KINDS.map(([k, t]) => `<button type="button" role="tab" data-fk="${k}" aria-selected="${f.kind === k}" class="${f.kind === k ? 'on' : ''}" ${KIND_TIP[k] ? `title="${KIND_TIP[k]}"` : ''}>${t}<span class="n">${n[k]}</span></button>`).join('')}</div>
      <label class="search">${ic('search', 15)}<input class="in" id="vq" type="search" placeholder="搜索名字、描述、音色 ID" value="${esc(f.q)}" aria-label="搜索音色"></label>
    </div>
    ${builtin ? `<div class="filters">
      ${dd('fprov', { value: f.model, cls: 'sel', label: '按模型筛选', width: 300, btnTags: false, groups: [{ items: [{ value: '', label: '所有模型' }] },
        ...(local.length ? [{ label: '本地', items: local.map(m => ({ value: m.id, html: mTitle(m), icon: mIcon(m), text: m.name })) }] : []),
        ...provs.map(pid => ({ label: pvName(pid), icon: pIcon(pid, 13), items: [{ value: 'p:' + pid, label: `${pvName(pid)} 的全部模型` }, ...ms.filter(m => m.provider === pid).map(m => ({ value: m.id, html: mTitle(m), icon: mIcon(m), text: m.name }))] }))],
        onChange: v => setVf(main, { model: v, lang: '' }) })}
      ${langs.length > 1 ? dd('flang', { value: f.lang, cls: 'sel', label: '按语言筛选', width: 240, groups: [{ items: [{ value: '', label: '所有语言' }, ...langs.map(([l, c]) => ({ value: l, label: langName(l), text: l, tags: [[String(c), 'mute']] }))] }], onChange: v => setVf(main, { lang: v }) }) : ''}
      <div class="seg" role="group" aria-label="按性别筛选">${[['', '不限'], ['女', '女声'], ['男', '男声']].map(([k, t]) => `<button type="button" data-fg="${k}" class="${f.gender === k ? 'on' : ''}" aria-pressed="${f.gender === k}">${t}</button>`).join('')}</div>
      <button type="button" class="chip fav ${f.fav ? 'on' : ''}" id="ffav" aria-pressed="${f.fav}">${ic('star', 13)}收藏 <span class="n">${S.settings.favorites.length}</span></button>
      ${f.model || f.lang || f.gender || f.fav || f.q ? '<button type="button" class="linkbtn" id="fclear">清除筛选</button>' : ''}
    </div>` : ''}
    ${builtin ? `<p class="sampleline" id="sampleLine">${ic('wave', 14)}<span>样本文本</span><q>${esc(S.settings.sample_text)}</q><button class="linkbtn" type="button" id="editSample">修改</button></p>` : ''}
    <div class="grid" id="vgrid"></div>
    <div class="more" id="more"></div>`;
  const grid = $('#vgrid', main), newTile = `<button class="vc vc-new" type="button" data-newclone>${ic('plus', 20)}<b>克隆一个新声音</b><span>上传或直接录一段 10–20 秒的录音</span></button>`;
  if (f.kind === 'clone') grid.innerHTML = vs.length || f.q || f.fav ? newTile + vs.slice(0, S.vlimit).map(voiceCard).join('') : '';
  if (f.kind === 'clone' && !S.clones.length) grid.outerHTML = `<div class="empty big">${ic('mic', 28)}<b>还没有克隆音色</b>上传或直接录一段 10–20 秒的录音（一个人说话、没有背景音乐），就能用这个声音说任何话。<br>录音存在本机；用本地模型时完全不出电脑。<div class="empty-a"><button class="btn primary" type="button" data-newclone>${ic('mic', 15)}克隆声音</button></div></div>`;
  else if (f.kind !== 'clone' && !vs.length) grid.outerHTML = f.kind === 'preset' && !f.q && !f.fav ? `<div class="empty big">${ic('layers', 28)}<b>还没有预设</b>在试音台调好音色、语气、语速后，点「存为预设」，就会出现在这里。<div class="empty-a"><a class="btn" href="#/playground">去试音台</a></div></div>`
    : S.voices.length ? `<div class="empty"><b>没有符合条件的音色</b>换个筛选条件试试。<div class="empty-a"><button class="btn" type="button" id="fclear2">清除筛选</button></div></div>`
    : '<div class="empty"><b>还没有能用的模型</b>去<a href="#/models/local">下载一个本地模型</a>，或<a href="#/models/openrouter">连接云端 Provider</a>。</div>';
  else if (f.kind !== 'clone') grid.innerHTML = vs.slice(0, S.vlimit).map(voiceCard).join('');
  if (vs.length > S.vlimit) $('#more', main).innerHTML = `<button class="btn" type="button" id="moreBtn">再显示 ${Math.min(60, vs.length - S.vlimit)} 个<span class="n">共 ${vs.length}</span></button>`;
  bindVoices(main, vs);
}
function voiceCard(v) {
  const m = M(v.model), ok = usable(m), fav = S.settings.favorites.includes(v.ref), clone = v.kind === 'clone';
  const c = clone ? S.clones.find(x => 'clone:' + x.id === v.ref) : null;
  const tags = clone ? [] : [v.kind === 'preset' ? '预设' : '', v.gender ? `${v.gender}声` : '', langName(v.lang)].filter(Boolean);
  const mname = m ? mName(m) : '';
  return `<article class="vc ${clone ? 'is-clone' : ''}" style="--m:${hue(v.model)}" data-ref="${esc(v.ref)}" data-url="${esc(v.sample.url)}">
    <div class="vc-top">
      <button class="pb" type="button" data-sample="${esc(v.ref)}" data-url="${esc(v.sample.url)}" ${ok ? '' : 'disabled'} aria-label="试听 ${esc(v.name)}" title="${clone ? `用 ${esc(mname)} 读样本文本` : '试听样本'}">${ic('play', 14)}</button>
      <div class="vc-name"><b>${esc(v.name)}</b><code>${esc(v.ref)}</code></div>
      <button class="star ${fav ? 'on' : ''}" type="button" data-fav="${esc(v.ref)}" aria-pressed="${fav}" aria-label="收藏 ${esc(v.name)}">${ic('star', 16)}</button>
    </div>
    ${clone ? `<p class="vc-text" title="录音的文字稿">${c?.text ? `「${esc(c.text)}」` : '<span class="mute">还没有文字稿：点「编辑」补上，克隆会更像</span>'}</p>
      <div class="vc-meta">${c ? `<span>录音 ${Math.round(c.duration)} 秒</span>` : ''}${m ? `<span class="mtag"><i class="dot"></i>${esc(mname)}</span>` : ''}${c?.consent ? '<span>有同意声明</span>' : ''}</div>`
      : `<p>${esc(v.description) || '<span class="mute">没有描述</span>'}</p>`}
    <canvas class="mini" data-url="${esc(v.sample.url)}" ${v.sample.cached ? '' : 'hidden'}></canvas>
    <div class="vc-foot">
      ${clone ? `<button class="btn ghost sm" type="button" data-orig="${esc(v.ref.slice(6))}" title="播放原始录音">${ic('mic', 13)}原声</button><button class="btn ghost sm" type="button" data-cedit="${esc(v.ref.slice(6))}">${ic('edit', 13)}编辑</button>`
        : `<span class="tags">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</span>`}
      <span class="sp"></span>
      ${ok ? `<a class="btn sm" href="#/playground" data-try="${esc(v.ref)}">试音${ic('arrow', 13)}</a>` : clone && !m ? `<a class="btn sm" href="#/models/local" title="克隆需要一个支持克隆的模型">下载克隆模型</a>` : `<a class="btn sm" href="#/models/${m?.provider || 'local'}">${m ? (m.provider === 'local' ? '去下载模型' : '去连接') : '模型已移除'}</a>`}
    </div></article>`;
}
function bindVoices(main, vs) {
  const vq = $('#vq', main); onText(vq, () => { S.vf.q = vq.value; store.set('vf', S.vf); S.vlimit = 60; pageVoices(main); const i = $('#vq', main); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 180);
  $$('[data-fk]', main).forEach(b => b.onclick = () => setVf(main, { kind: b.dataset.fk }));
  $$('[data-fg]', main).forEach(b => b.onclick = () => setVf(main, { gender: b.dataset.fg }));
  const ff = $('#ffav', main); if (ff) ff.onclick = () => setVf(main, { fav: !S.vf.fav });
  $$('#fclear, #fclear2', main).forEach(b => b.onclick = () => setVf(main, { model: '', lang: '', gender: '', fav: false, q: '' }));
  const more = $('#moreBtn', main); if (more) more.onclick = () => { S.vlimit += 60; pageVoices(main); };
  $$('[data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy, '已复制命令'));
  $$('[data-sample]', main).forEach(b => b.onclick = () => playSample(b.dataset.sample, b));
  $$('[data-fav]', main).forEach(b => b.onclick = () => toggleFav(b.dataset.fav, b));
  $$('[data-try]', main).forEach(a => a.onclick = () => tryVoice(a.dataset.try));
  $$('canvas.mini:not([hidden])', main).forEach(cv => drawWave(cv, cv.dataset.url));
  $$('#toClone, [data-newclone]', main).forEach(b => b.onclick = () => openCloneSheet(main));
  $$('[data-orig]', main).forEach(b => b.onclick = () => playOrig(b.dataset.orig));
  $$('[data-cedit]', main).forEach(b => b.onclick = () => openCloneSheet(main, b.dataset.cedit));
  const es = $('#editSample', main); if (es) es.onclick = () => {
    const line = $('#sampleLine', main);
    line.classList.add('editing');
    line.innerHTML = `<input class="in" id="sampleIn" value="${esc(S.settings.sample_text)}" aria-label="样本文本"><button class="btn primary sm" type="button" id="saveSample">保存</button><button class="btn ghost sm" type="button" id="cancelSample">取消</button><span class="note">{name} 会替换成音色名字。改动后，样本在下次试听时按新文本重新生成。</span>`;
    const si = $('#sampleIn', line); si.focus(); si.select();
    $('#cancelSample', line).onclick = () => pageVoices(main);
    const save = async () => { S.settings = await api('/api/settings', { sample_text: si.value.trim() }); await refreshVoices(); pageVoices(main); toast('样本文本已更新'); };
    $('#saveSample', line).onclick = save;
    si.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) save(); if (e.key === 'Escape') pageVoices(main); };
  };
}
const playOrig = id => { const c = S.clones.find(x => x.id === id); if (c) play(c.sample + '?r=' + c.rev, { title: c.name, sub: `clone:${c.id} · 原始录音`, color: hue('clone') }); };

/* ---------- 侧边面板（克隆音色的新建与编辑） ---------- */
const SHEET = $('#sheet');
function openSheet(html, onClose) {
  SHEET.innerHTML = html; SHEET._onClose = onClose;
  if (!SHEET.open) SHEET.showModal();
  return SHEET;
}
function closeSheet() { if (SHEET.open) SHEET.close(); }
SHEET.addEventListener('close', () => { const f = SHEET._onClose; SHEET._onClose = null; SHEET.innerHTML = ''; f?.(); });
SHEET.addEventListener('click', e => { if (e.target === SHEET) closeSheet(); });   // 点遮罩关闭
const sheetHead = (title, sub) => `<header class="sh-h"><div><h2 id="shTitle">${title}</h2>${sub ? `<p>${sub}</p>` : ''}</div><button class="btn ghost icon" type="button" data-shclose aria-label="关闭">${ic('x', 18)}</button></header>`;

/* ---------- 克隆音色：上传或录一段声音 ---------- */
/* 支持克隆的模型：本地在前；默认选能用的本地模型（不花钱、录音不出电脑） */
const cloneModels = () => S.models.filter(m => isTTS(m) && m.caps.clone).sort((a, b) => (a.provider !== 'local') - (b.provider !== 'local'));
const cloneDefault = () => { const ms = cloneModels(); return (ms.find(m => m.provider === 'local' && usable(m)) || ms.find(usable) || ms[0])?.id; };
function cloneModelSelect(id, cur, onChange) {
  return dd(id, { value: cur, label: '克隆用的模型', groups: modelGroups(cloneModels(), { caps: false }).map(g => ({ ...g, items: g.items.map(it => ({ ...it, sub: M(it.value).provider === 'local' ? '本机运行，录音不出电脑' : '用时上传录音到这家' })) })), onChange });
}
/* 选中模型的说明：在哪里运行、要不要上传、收不收费、要不要同意声明 */
function cloneModelNote(m) {
  if (!m) return '';
  const pv = PV(m.provider)?.name || m.provider;
  if (m.provider === 'local') return usable(m) ? '在本机运行，录音不出电脑。' : `还没下载（约 ${m.size_gb} GB）。可以先建好，<a href="#/models/local">下载</a>后就能用。`;
  if (!usable(m)) return `${esc(pv)} 还没连接。可以先建好，<a href="#/models/${m.provider}">连接</a>后再用。`;
  return [`第一次用时会把录音上传给 ${esc(pv)}，之后复用那边的音色。`, m.clone?.fee ? `收费：${esc(m.clone.fee)}，使用前会再确认。` : '', m.clone?.consent ? '这家要求一段同意声明录音（见下方）。' : ''].filter(Boolean).join('');
}
function consentBlock(m, have) {
  const ph = m?.clone?.consent; if (!ph) return '';
  return `<div class="cn-consent"><div class="lbl"><span>同意声明录音（${esc(PV(m.provider)?.name || m.provider)} 要求）${have ? ' · 已上传，可替换' : ''}</span></div>
    <p class="note">请声音的主人本人逐字朗读下面这句并录下来，和上面的录音用同一支麦克风、在同一个环境里录。</p>
    <q class="consent">${esc(ph.zh)}</q><input type="file" accept="audio/*" class="in" data-consent></div>`;
}
const cloneNoteAll = '换模型不用重录：这个声音以后在任何支持克隆的模型上都能用，这里选的是试听和默认用的那个。';
function cloneForm() {
  const c = S.cn, f = c.file;
  if (!c.model || !M(c.model)) c.model = cloneDefault();
  const cm = M(c.model);
  return `${sheetHead('克隆一个声音', '录音存在本机；只有用云端模型说话时，才会上传给那一家。')}
    <div class="sh-b">
      <section class="sh-sec"><h3><i>1</i>录音</h3>
        <ul class="cn-tips"><li>10–20 秒</li><li>只有一个人说话</li><li>没有背景音乐和回声</li></ul>
        <div class="cn-src">
          <label class="drop ${f ? 'has' : ''}" id="cnDrop"><input type="file" id="cnFile" accept="audio/*,video/*" hidden>
            <span class="drop-ic">${ic(f ? 'wave' : 'upload', 22)}</span>
            ${f ? `<span class="drop-t"><b>${esc(f.name)}</b><span>${(f.size / 1e6).toFixed(1)} MB · 点这里换一个</span></span>` : '<span class="drop-t"><b>拖入录音，或点这里选择</b><span>m4a、mp3、wav、mp4……ffmpeg 能读的都行</span></span>'}</label>
          <span class="cn-or">或</span>
          <button class="btn ${c.rec ? 'rec' : ''}" type="button" id="cnRec">${c.rec ? `<i class="rec-dot"></i>停止 <span id="cnT" class="mono">0:00</span>` : `${ic('mic', 15)}直接录音`}</button>
        </div>
        ${c.url ? `<audio controls src="${c.url}" class="cn-audio"></audio>` : ''}
      </section>
      <section class="sh-sec"><h3><i>2</i>名字和文字稿</h3>
        <div class="field"><div class="lbl"><span>名字</span></div><input class="in" id="cnName" value="${esc(c.name || '')}" placeholder="比如：旁白、主持人"></div>
        <div class="field"><div class="lbl"><span>文字稿</span><span class="key">录音里说了什么，可不填</span></div>
          <textarea class="in" id="cnText" rows="3" placeholder="留空会用本地识别模型自动生成；有一字不差的文字稿，克隆会更像">${esc(c.text || '')}</textarea></div>
      </section>
      <section class="sh-sec"><h3><i>3</i>用哪个模型</h3>
        <div class="field">${cloneModelSelect('cnModel', c.model, v => { S.cn.model = v; const y = $('.sh-b', SHEET)?.scrollTop; SHEET.innerHTML = cloneForm(); bindCloneForm($('#main')); if (y) $('.sh-b', SHEET).scrollTop = y; })}<span class="note" id="cnModelNote">${cloneModelNote(cm)}</span><span class="note">${cloneNoteAll}</span></div>
        ${consentBlock(cm, !!c.consent)}
      </section>
    </div>
    <footer class="sh-f">
      <label class="cn-ok"><input type="checkbox" id="cnOk" ${c.ok ? 'checked' : ''}> 这是我本人的声音，或我已得到声音主人的同意</label>
      <div class="sh-a"><span class="note" id="cnHint">${!f ? '先选一段录音' : !c.ok ? '勾选上面的确认后才能创建' : ''}</span><span class="sp"></span>
        <button class="btn ghost" type="button" data-shclose>取消</button>
        <button class="btn primary" type="button" id="cnGo" ${f && c.ok && !c.busy ? '' : 'disabled'}>${c.busy ? '<span class="spin"></span>正在处理…' : '创建克隆音色'}</button></div>
    </footer>`;
}
function openCloneSheet(main, id) {
  if (id) return editClone(id, main);
  const stopRec = () => { if (S.cn.rec) { S.cn.discard = true; S.cn.rec.stop(); } };
  openSheet(cloneForm(), stopRec);
  bindCloneForm(main);
}
function bindCloneForm(main) {
  const box = SHEET, c = S.cn, redraw = () => { const y = $('.sh-b', box)?.scrollTop; box.innerHTML = cloneForm(); bindCloneForm(main); if (y) $('.sh-b', box).scrollTop = y; };
  const pick = f => { if (c.url) URL.revokeObjectURL(c.url); Object.assign(c, { file: f, url: URL.createObjectURL(f), name: c.name || f.name.replace(/\.[^.]+$/, '') }); redraw(); };
  $$('[data-shclose]', box).forEach(b => b.onclick = closeSheet);
  const inp = $('#cnFile', box), drop = $('#cnDrop', box);
  inp.onchange = () => inp.files[0] && pick(inp.files[0]);
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) pick(f); };
  onText($('#cnName', box), () => c.name = $('#cnName', box).value);
  onText($('#cnText', box), () => c.text = $('#cnText', box).value);
  const cs = $('[data-consent]', box); if (cs) cs.onchange = e => c.consent = e.target.files[0] || null;
  $('#cnOk', box).onchange = e => { c.ok = e.target.checked; redraw(); };
  $('#cnRec', box).onclick = async () => {
    if (c.rec) return c.rec.stop();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }), chunks = [], t0 = Date.now();
      const r = c.rec = new MediaRecorder(stream);
      r.ondataavailable = e => chunks.push(e.data);
      r.onstop = () => { stream.getTracks().forEach(t => t.stop()); clearInterval(c.tick); c.rec = null;
        if (c.discard) { c.discard = false; return; }   // 录音中关掉面板：丢弃这段
        const type = r.mimeType || 'audio/webm', f = new File(chunks, `录音-${new Date().toLocaleTimeString('zh-CN', { hour12: false }).replace(/:/g, '')}.${type.includes('mp4') ? 'm4a' : 'webm'}`, { type });
        pick(f); };
      r.start(); redraw();
      c.tick = setInterval(() => { const el = $('#cnT', box), s = Math.floor((Date.now() - t0) / 1000); if (el) el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 250);
    } catch (e) { toast(`没法录音：${e.message}（检查浏览器的麦克风权限）`, 5000); }
  };
  $('#cnGo', box).onclick = async () => {
    if (!c.file || !c.ok || c.busy) return;
    const fd = new FormData();
    fd.append('file', c.file, c.file.name);
    if (c.name?.trim()) fd.append('name', c.name.trim());
    if (c.model) fd.append('model', c.model);
    if (c.text?.trim()) fd.append('text', c.text.trim());
    if (c.consent) fd.append('consent', c.consent, c.consent.name);
    c.busy = true; redraw();
    try {
      const r = await fetch('/api/clones', { method: 'POST', body: fd }), j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
      if (c.url) URL.revokeObjectURL(c.url);
      S.cn = { file: null, url: null, rec: null, model: c.model };
      closeSheet(); await refreshVoices(); S.vf.kind = 'clone'; store.set('vf', S.vf); if (S.route === 'voices') pageVoices(main);
      toast(j.text_auto ? `已创建「${j.name}」。文字稿是自动识别的，不准的话点「编辑」改一下` : `已创建「${j.name}」`, 5000);
    } catch (e) { c.busy = false; redraw(); toast(`创建失败：${e.message}`, 6000); }
  };
}
function editClone(id, main) {
  const c = S.clones.find(x => x.id === id); if (!c) return;
  const v = S.voices.find(x => x.ref === 'clone:' + id), cur = c.model && M(c.model) ? c.model : v?.model || cloneDefault(), st = { model: cur };
  const box = openSheet(`${sheetHead(`编辑「${esc(c.name)}」`, `<code>clone:${esc(c.id)}</code> · 录音 ${Math.round(c.duration)} 秒${c.file ? ` · 来自 ${esc(c.file)}` : ''}`)}
    <div class="sh-b">
      <section class="sh-sec"><h3>原始录音</h3><audio controls src="${esc(c.sample)}?r=${esc(c.rev)}" class="cn-audio"></audio></section>
      <section class="sh-sec">
        <div class="field"><div class="lbl"><span>名字</span></div><input class="in" value="${esc(c.name)}" data-k="name"></div>
        <div class="field"><div class="lbl"><span>文字稿</span><span class="key">${c.text_auto ? '自动识别的，请核对' : '录音里说了什么'}</span></div>
          <textarea class="in" rows="4" data-k="text">${esc(c.text || '')}</textarea>
          <span class="note">要和录音一字不差；改了之后，云端模型下次使用时会重新上传。</span></div>
      </section>
      <section class="sh-sec"><h3>用哪个模型</h3>
        <div class="field">${cloneModelSelect('ceModel', cur, v => { st.model = v; const m = M(v); $('[data-k=mnote]', SHEET).innerHTML = cloneModelNote(m); $('[data-k=consentBox]', SHEET).innerHTML = consentBlock(m, c.consent); })}<span class="note" data-k="mnote">${cloneModelNote(M(cur))}</span><span class="note">${cloneNoteAll}</span></div>
        <div data-k="consentBox">${consentBlock(M(cur), c.consent)}</div>
      </section>
    </div>
    <footer class="sh-f"><div class="sh-a"><button class="btn ghost danger" type="button" data-k="del">删除这个声音</button><span class="sp"></span>
      <button class="btn ghost" type="button" data-shclose>取消</button><button class="btn primary" type="button" data-k="save">保存</button></div></footer>`);
  $$('[data-shclose]', box).forEach(b => b.onclick = closeSheet);
  $('[data-k=save]', box).onclick = async e => {
    const b = e.currentTarget; b.disabled = true;
    try {
      await api('/api/clones/update', { id, name: $('[data-k=name]', box).value, text: $('[data-k=text]', box).value, model: st.model });
      const cf = $('[data-consent]', box)?.files[0];
      if (cf) { const fd = new FormData(); fd.append('id', id); fd.append('consent', cf, cf.name); const r = await fetch('/api/clones/consent', { method: 'POST', body: fd }), j = await r.json(); if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`); }
      closeSheet(); await refreshVoices(); if (S.route === 'voices') pageVoices(main); toast('已保存');
    }
    catch (err) { b.disabled = false; toast(`保存失败：${err.message}`, 5000); }
  };
  const del = $('[data-k=del]', box);
  del.onclick = async () => {
    const up = Object.keys(c.remote || {});
    if (!del.classList.contains('armed')) {   // 删除录音：原地二次确认
      del.classList.add('armed'); del.textContent = `确认删除？录音和文字稿会一起删掉${up.length ? `，并尝试删除在 ${up.join('、')} 注册的音色` : ''}`;
      clearTimeout(del._t); del._t = setTimeout(() => { del.classList.remove('armed'); del.textContent = '删除这个声音'; }, 5000); return;
    }
    try { const r = await api('/api/clones/delete', { id }); closeSheet(); await refreshVoices(); if (S.route === 'voices') pageVoices(main); toast(r.remote_failed?.length ? `已删除；云端没删掉：${r.remote_failed.join('；')}` : '已删除', 5000); }
    catch (err) { toast(`删除失败：${err.message}`, 5000); }
  };
}
async function playSample(ref, btn) {
  const v = S.voices.find(x => x.ref === ref); if (!v) return;
  const meta = { title: v.name, sub: `${v.ref} · 样本`, color: hue(v.model) };
  if (v.sample.cached) return play(v.sample.url, meta);
  const others = $$(`.pb[data-sample="${CSS.escape(ref)}"]`); others.forEach(b => { b.classList.add('busy'); b.innerHTML = ''; b.dataset.st = ''; });
  const m = M(v.model), slow = m && m.provider === 'local' && m.status !== 'loaded';
  toast(m?.provider !== 'local' ? `正在用 ${PV(m.provider)?.name || m.provider} 生成样本（云端计费，${estimateLocal({ model: m.id, input: S.settings.sample_text }) || '按官方价格'}）…` : slow ? `第一次用 ${m.name}，正在加载模型并生成样本…` : '正在生成样本…', 4000);
  try {
    await api('/api/voices/sample', { ref }); v.sample.cached = true;
    $$(`.vc[data-ref="${CSS.escape(ref)}"] canvas.mini`).forEach(c => { c.hidden = false; drawWave(c, c.dataset.url); });
    play(v.sample.url, meta); if (slow) { refreshModels(); refreshStatus(); }
  } catch (e) { toast(`样本生成失败：${e.message}`, 5000); }
  finally { others.forEach(b => b.classList.remove('busy')); }
}
async function toggleFav(ref, btn) {
  const f = new Set(S.settings.favorites); f.has(ref) ? f.delete(ref) : f.add(ref);
  S.settings = await api('/api/settings', { favorites: [...f] });
  if (btn) { const on = S.settings.favorites.includes(ref); btn.classList.toggle('on', on); btn.setAttribute('aria-pressed', on); }
  const ff = $('#ffav .n'); if (ff) ff.textContent = S.settings.favorites.length;
}
/* ============ 试音台 ============
   一段文字 + 一个或几个声音。每个声音是一份完整配方（模型、音色、语气、语速、种子……）：
   右侧面板编辑选中的那个，列表里并排听，放几个就是对比；满意的存为预设，或拿走调用代码。
   历史（命令行、API 生成的也在里面）在下面，可以复现，也可以加入对比。 */
const cid = () => Math.random().toString(36).slice(2, 8);
const LETTER = i => String.fromCharCode(65 + i);
const trunc = (t, n) => { const a = [...String(t || '')]; return a.length > n ? a.slice(0, n).join('') + '…' : a.join(''); };
function newSlot(p = {}) {
  const model = M(p.model)?.id || (mineTTS().find(m => usable(m) && m.caps.voices) || mineTTS()[0] || S.models.find(isTTS))?.id;
  const m = M(model);
  return { model, voice: p.voice || m?.default_voice || (m?.caps.clone && !m.caps.voices && S.clones[0] ? 'clone:' + S.clones[0].id : ''), instructions: p.instructions || '', speed: p.speed ?? 1, seedMode: p.seed != null ? 'fixed' : 'random',
    seed: p.seed ?? Math.floor(Math.random() * 1e6), lang: p.lang || 'chinese', ...GEN_DEFAULT, ...Object.fromEntries(Object.keys(GEN_DEFAULT).filter(k => p[k] != null).map(k => [k, p[k]])) };
}
// 新声音：from = 沿用它的语气、语速和种子（比较时只差音色或模型）
function newCand(p = {}, from) {
  const c = { ...newSlot(p), id: cid() }, m = M(c.model), fm = from && M(from.model);
  if (fm) {
    if (p.instructions == null && !m?.caps.design && !fm.caps.design) c.instructions = from.instructions || '';
    if (p.speed == null) c.speed = from.speed;
    if (p.seed == null) Object.assign(c, { seedMode: from.seedMode, seed: from.seed });
  }
  return c;
}
// 旧版：单路的 slots[0]；对比的 cands（参数可能跟随统一设置 cmpBase / 统一种子 cmpSeed）
function migrateWs() {
  const base = store.get('cmpBase', null) || {}, seed = store.get('cmpSeed', null), single = (store.get('slots', null) || [])[0];
  const old = (store.get('cands', null) || []).map(c => ({ ...c, instructions: c.instructions ?? base.instructions ?? '', speed: c.speed ?? base.speed ?? 1, ...(c.seedMode === 'shared' ? { seedMode: seed != null ? 'fixed' : 'random', seed: seed ?? c.seed } : {}) }));
  const cands = (single ? [{ ...single, id: cid() }] : old).map(c => { const x = { ...c }; delete x.of; return x; });
  return { cands, cur: cands[0]?.id };
}
const doneRes = o => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v?.rec));   // 只存生成好的；排队、生成中、失败都不跨刷新保留
Object.assign(S, { ws: store.get('ws', null) || migrateWs(), res: doneRes(store.get('cmpRes', {})), histStar: false, histLimit: 30 });
const saveWs = () => {
  store.set('ws', S.ws);
  const d = doneRes(S.res), ks = Object.keys(d); ks.slice(0, Math.max(0, ks.length - 300)).forEach(k => { delete d[k]; delete S.res[k]; }); store.set('cmpRes', d);
};
function ensureWs() {
  const w = S.ws; w.cands = (w.cands || []).filter(c => M(c.model) && isTTS(M(c.model)));
  if (!w.cands.length) { const c = newCand(); if (!M(c.model)) return false; w.cands = [c]; }
  if (!w.cands.some(c => c.id === w.cur)) w.cur = w.cands[0].id;
  return true;
}
const cur = () => S.ws.cands.find(c => c.id === S.ws.cur) || S.ws.cands[0];
const tagOf = c => LETTER(S.ws.cands.indexOf(c));
const candName = c => { const m = M(c.model); return c.voice && (m.caps.voices || String(c.voice).startsWith('clone:')) ? voiceName(m.id, c.voice) : m.caps.design ? '声音设计' : '默认音色'; };
const recName = r => { const m = M(r.model); return r.voice ? voiceName(r.model, r.voice) : m?.caps.design ? '声音设计' : '默认音色'; };
// 加进试音台：已有同样的声音就选中它；只有一个还没生成过的声音时直接替换，否则追加
function addToWs(p, { exact = false } = {}) {
  ensureWs(); const w = S.ws, mid = M(p.model)?.id;
  const same = w.cands.find(c => c.model === mid && (c.voice || '') === (p.voice || '') && (!exact || (c.instructions || '') === (p.instructions || '')));
  if (same) { w.cur = same.id; saveWs(); return 'exists'; }
  const c = exact ? newCand(p) : newCand(p, cur());
  const fresh = w.cands.length === 1 && !w.cands[0].last && !pending(resOf(w.cands[0]));
  w.cands = fresh ? [c] : [...w.cands, c]; w.cur = c.id; saveWs();
  return fresh ? 'replaced' : 'added';
}
function tryVoice(ref) {
  const v = S.voices.find(x => x.ref === ref); if (!v) return;
  if (addToWs(v.request || { model: v.model, voice: v.voice }, { exact: !!v.request }) === 'added') toast(`已加入试音台，现在有 ${S.ws.cands.length} 个声音`);
}

function reqOf(s, text) {
  const m = M(s.model), has = k => m.params.includes(k), r = { model: m.id, input: text ?? S.text };
  if (has('voice') && s.voice) r.voice = s.voice;
  if (has('instructions') && (s.instructions || '').trim()) r.instructions = s.instructions.trim();
  if (has('speed') && Number(s.speed) !== 1) r.speed = Number(s.speed);
  if (has('seed') && s.seedMode === 'fixed') r.seed = Number(s.seed);
  if (has('lang') && s.lang !== 'chinese') r.lang = s.lang;
  Object.keys(GEN_DEFAULT).forEach(k => { if (has(k) && Number(s[k]) !== GEN_DEFAULT[k]) r[k] = Number(s[k]); });
  return r;
}
const shq = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
function cmdOf(r, kind) {
  const ext = Object.fromEntries(Object.entries(r).filter(([k]) => !['model', 'input', 'voice', 'instructions', 'speed'].includes(k)));
  if (kind === 'cli') {
    const flag = { voice: '-v', instructions: '-i', speed: '-s', seed: '--seed', lang: '-l', temperature: '--temperature', top_p: '--top-p', top_k: '--top-k', repetition_penalty: '--repetition-penalty' };
    return ['vox say', shq(r.input), '-m', short(M(r.model)), ...Object.entries(r).filter(([k]) => flag[k]).flatMap(([k, v]) => [flag[k], typeof v === 'string' ? shq(v) : v]), '-o out.mp3'].join(' ');
  }
  if (kind === 'curl') return `curl ${ORIGIN}/v1/audio/speech \\\n  -H "Content-Type: application/json" \\\n  -d ${shq(JSON.stringify({ ...r, response_format: 'mp3' }))} \\\n  -o out.mp3`;
  const py = [`from openai import OpenAI`, ``, `client = OpenAI(base_url="${ORIGIN}/v1", api_key="vox")  # 本地服务不校验 key`, `with client.audio.speech.with_streaming_response.create(`,
    `    model=${JSON.stringify(r.model)},`, r.voice ? `    voice=${JSON.stringify(r.voice)},` : `    voice="",`, `    input=${JSON.stringify(r.input)},`,
    r.instructions ? `    instructions=${JSON.stringify(r.instructions)},` : null, r.speed ? `    speed=${r.speed},` : null,
    Object.keys(ext).length ? `    extra_body=${JSON.stringify(ext)},  # vox 扩展参数` : null, `) as resp:`, `    resp.stream_to_file("out.mp3")`];
  return py.filter(x => x !== null).join('\n');
}
async function savePreset(r) {
  r = { ...r }; delete r.input;
  const name = `${recName(r)}${r.instructions && !M(r.model).caps.design ? ' · ' + trunc(r.instructions, 10) : ''}`;
  if (M(r.model).caps.seed && r.seed == null) toast('提示：当前是「每次随机」种子，存下的预设每次听起来会略有不同。固定一个满意的种子再存更稳。', 5000);
  try { const rec = await api('/api/presets', { name, request: r }); await refreshVoices(); toast(`已存为预设「${rec.name}」：音色库「预设」里能找到，命令行写 -v preset:${rec.id}`, 5000); }
  catch (e) { toast(`保存失败：${e.message}`, 5000); }
}

/* ---------- 请求、结果与生成队列 ---------- */
const candReq = c => reqOf(c, S.text.trim());
const rkey = r => JSON.stringify(Object.keys(r).sort().map(k => [k, r[k]]));
const resOf = c => S.res[rkey(candReq(c))];
const pending = res => res?.rec || res?.busy || res?.queued;
const histRec = id => S.hist.find(h => h.id === id);
const slim = r => ({ id: r.id, dur: r.dur, elapsed: r.elapsed, cost: r.cost, request: r.request, cached: r.cached, ts: r.ts });
const needsDesc = c => M(c.model).caps.design && !(c.instructions || '').trim();
const canRun = c => usable(M(c.model)) && !needsDesc(c) && !!S.text.trim();
const regen = c => !M(c.model).params.includes('seed') || c.seedMode !== 'fixed';   // 再来一版有意义：随机种子，或模型不支持种子
const recMeta = r => ({ title: `${recName(r.request)} · ${trunc(r.request.input, 24)}`, sub: `${mName(M(r.request.model))}${r.request.instructions ? ' · ' + r.request.instructions : ''}${r.request.seed != null ? ' · 种子 ' + r.request.seed : ''}`, color: hue(r.request.model) });
/* 并行生成：云端每家同时 3 条；本地模型共用一块 GPU（服务端本来就串行），按顺序一条条送。同一时间最多 4 个请求在路上。 */
const GENQ = { wait: [], run: new Map() };
const LANE_MAX = { local: 1 }, CLOUD_MAX = 3, TOTAL_MAX = 4;
function enqueue(c, { front = false, autoplay = false, force = false } = {}) {
  const r = candReq(c), k = rkey(r), res = S.res[k], waiting = GENQ.wait.find(j => j.k === k);
  if (waiting) { if (front) GENQ.wait = [waiting, ...GENQ.wait.filter(j => j !== waiting)]; waiting.autoplay ||= autoplay; return pump(); }
  if (res?.busy || (res?.rec && !force)) return;
  const job = { k, r, cid: c.id, autoplay, force, lane: M(r.model).provider };
  S.res[k] = { queued: true };
  if (front) GENQ.wait.unshift(job); else GENQ.wait.push(job);
  pump();
}
function pump() {
  for (const job of [...GENQ.wait]) {
    if (GENQ.run.size >= TOTAL_MAX) break;
    if ([...GENQ.run.values()].filter(l => l === job.lane).length >= (LANE_MAX[job.lane] ?? CLOUD_MAX)) continue;
    GENQ.wait = GENQ.wait.filter(j => j !== job); GENQ.run.set(job.k, job.lane); runJob(job);
  }
  wsRefresh();
}
async function runJob(job) {
  const m = M(job.r.model), cold = m.provider === 'local' && m.status !== 'loaded';
  S.res[job.k] = { busy: true, cold }; wsRefresh();
  let rec = null;
  try {
    rec = await speech({ ...job.r, source: 'webui', ...(job.force ? { cache: false } : {}) });
    S.res[job.k] = { rec: slim(rec) }; S.hist = [rec, ...S.hist.filter(h => h.id !== rec.id)];
    const c = S.ws.cands.find(x => x.id === job.cid); if (c) c.last = slim(rec);
  } catch (e) { S.res[job.k] = { err: e.message }; if (job.autoplay) toast(`生成失败：${e.message}`, 5000); }
  GENQ.run.delete(job.k); saveWs();
  if (cold) { refreshModels(); refreshStatus(); }
  if (rec && job.autoplay && S.route === 'playground') play(`/clips/${rec.id}.wav`, recMeta(rec));
  if (rec && S.autoAsr && S.status?.asr) runAsr(rec.id);
  pump(); renderHist();
}
function cancelQueue() { GENQ.wait.forEach(j => delete S.res[j.k]); GENQ.wait = []; wsRefresh(); }
// 主按钮：有没生成的就生成它们；都生成过了，就给能换一版的（随机种子）再来一版
function wsPlan() {
  if (!S.text.trim()) return { todo: [], again: [] };
  const ok = S.ws.cands.filter(c => usable(M(c.model)) && !needsDesc(c));
  const todo = [...new Map(ok.filter(c => !pending(resOf(c))).map(c => [rkey(candReq(c)), c])).values()];
  return { todo, again: todo.length ? [] : ok.filter(c => resOf(c)?.rec && regen(c)) };
}
function generate() {
  const { todo, again } = wsPlan(), solo = S.ws.cands.length === 1;
  if (todo.length) todo.forEach(c => enqueue(c, { autoplay: solo }));
  else again.forEach(c => enqueue(c, { force: true, autoplay: solo }));
}

/* ---------- 页面 ---------- */
const EX_N = 6;
function pagePlayground(main) {
  if (!ensureWs()) {
    main.innerHTML = `<div class="head"><div><h1>试音台</h1></div></div><div class="empty big">${ic('box', 28)}<b>还没有能用的语音合成模型</b>下载一个本地模型，下载后离线运行；或者连接一家云端服务。<div class="empty-a"><a class="btn primary" href="#/models/local">下载本地模型</a><a class="btn" href="#/models/openrouter">连接云端</a></div></div>`;
    return;
  }
  main.innerHTML = `
    <div class="head"><div><h1>试音台</h1><p>写一段文字，配一个或几个声音，生成后并排听。右侧调整选中的声音；满意的存为预设，在音色库、命令行和 API 里都能直接用。</p></div></div>
    <div class="ws">
      <div class="compose">
        <textarea class="in" id="text" aria-label="要合成的文字" placeholder="输入要合成的文字…">${esc(S.text)}</textarea>
        <div class="compose-go">
          <span class="count" id="count"></span>
          ${dd('quick', { menu: true, cls: 'btn ghost sm', trigger: `换个示例${ICV}`, width: 300, groups: [{ items: QUICK.map((q, i) => ({ value: i, label: q })) }], onChange: i => { const ta = $('#text'); ta.value = S.text = QUICK[i]; store.set('text', S.text); wsRefresh(); ta.focus(); } })}
          <span class="sp"></span><span class="hint" id="hint"></span>
          <button class="btn primary lg" type="button" id="gen"></button>
        </div>
      </div>
      <section class="tracks" aria-labelledby="tkTitle">
        <div class="sec-t"><h2 id="tkTitle">声音</h2><span class="n" id="tkN"></span><span class="sp"></span>
          <label class="switch" title="生成后用本地识别模型把音频转回文字，标出读错的字"><input type="checkbox" id="autoAsr" ${S.autoAsr ? 'checked' : ''}><i></i>自动校对读音</label>
          <button class="btn sm" type="button" data-addv>${ic('plus', 14)}添加声音</button></div>
        <div class="tk-list" id="tkList"></div>
      </section>
      <aside class="insp" id="insp" aria-label="选中声音的参数"></aside>
      <section class="hist" id="hist" aria-label="历史"></section>
    </div>`;
  const ta = $('#text', main);
  onText(ta, () => { S.text = ta.value; store.set('text', S.text); wsRefresh(); }, 120);
  ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); generate(); } };
  $('#gen', main).onclick = generate;
  $('#autoAsr', main).onchange = e => { S.autoAsr = e.target.checked; store.set('autoAsr', S.autoAsr); };
  main.onclick = e => {   // 列表、历史的点击都在这里分派
    const t = e.target, at = s => t.closest(s);
    if (at('[data-addv]')) return openAddVoices();
    if (at('#cancelQ')) return cancelQueue();
    const tk = at('.tk');
    if (tk) {
      const c = S.ws.cands.find(x => x.id === tk.dataset.tk); if (!c) return;
      if (at('[data-tplay]')) { const res = resOf(c); return res?.rec ? play(`/clips/${res.rec.id}.wav`, recMeta(histRec(res.rec.id) || res.rec)) : enqueue(c, { front: true, autoplay: true }); }
      if (at('[data-tagain]')) return enqueue(c, { force: true, front: true, autoplay: true });
      if (at('[data-tstar]')) return starRec(at('[data-tstar]').dataset.tstar);
      const cv = at('canvas.wave'); if (cv) { const r = cv.getBoundingClientRect(), rec = histRec(cv.dataset.id) || resOf(c)?.rec || c.last; return rec && play(cv.dataset.url, recMeta(rec), (e.clientX - r.left) / r.width); }
      if (at('button, a, [data-dd]')) return;
      if (S.ws.cur !== c.id) { S.ws.cur = c.id; saveWs(); renderTracks(); renderInsp(); }
      return;
    }
    const hr = at('.hr'); if (!hr) return;
    const h = histRec(hr.dataset.h); if (!h) return;
    if (at('[data-hplay]')) return play(`/clips/${h.id}.wav`, recMeta(h));
    if (at('[data-hadd]')) return histAct('add', h);
    if (at('[data-hstar]')) return starRec(h.id);
    if (at('[data-asr]')) return runAsr(h.id);
  };
  renderInsp(); wsRefresh(); renderHist();
  // 命令行、API 生成的结果也进同一份历史：每次进试音台重新取一次，不用刷新页面
  api('/api/history?limit=200').then(h => { if (S.route !== 'playground' || JSON.stringify(h.map(x => x.id)) === JSON.stringify(S.hist.map(x => x.id))) return; S.hist = h; renderHist(); renderTracks(); }).catch(() => {});
}
function wsRefresh() { if (S.route !== 'playground' || !$('#tkList')) return; renderTracks(); renderGo(); }
function renderGo() {
  const g = $('#gen'); if (!g) return;
  $('#count').textContent = S.text.trim() ? `${[...S.text].length} 字` : '';
  const { todo, again } = wsPlan(), cs = S.ws.cands, run = GENQ.run.size, wait = GENQ.wait.length;
  const ests = todo.map(c => estimateNum(candReq(c))).filter(Boolean), sum = {};
  ests.filter(e => !e.token).forEach(e => sum[e.cur] = (sum[e.cur] || 0) + e.v);
  const cost = Object.entries(sum).map(([c, v]) => money(v, c)), tok = ests.some(e => e.token);
  const bad = cs.filter(c => !usable(M(c.model))).length, desc = cs.filter(needsDesc).length;
  const hint = !S.text.trim() ? '先输入文字'
    : run || wait ? `生成中 ${run} 个${wait ? `，排队 ${wait} 个 · <button class="linkbtn" type="button" id="cancelQ">取消排队</button>` : ''}`
    : todo.length ? [cost.length ? `云端约 ${cost.join(' + ')}` : tok ? '按 token 计费' : todo.every(c => M(c.model).provider === 'local') ? '本机生成，免费' : '',
      todo.some(c => M(c.model).provider === 'local' && M(c.model).status !== 'loaded') ? '第一次要先加载模型' : ''].filter(Boolean).join(' · ')
    : bad ? `${bad} 个声音的模型不能用` : desc ? '声音设计要先写描述' : '';
  $('#hint').innerHTML = hint;
  const busy = run || wait;
  g.disabled = busy || (!todo.length && !again.length);
  g.title = !todo.length && !again.length && S.text.trim() ? '文字和参数都没变；固定种子会得到同样的结果' : '';
  g.innerHTML = busy ? '<span class="spin"></span>生成中…' : `${ic(todo.length || !again.length ? 'play' : 'refresh', 14)}${todo.length ? (todo.length > 1 ? `生成 ${todo.length} 个声音` : '生成') : again.length ? '再来一版' : '已是最新'}<kbd>⌘↵</kbd>`;
}
// 声音上的胶囊标签：模型最醒目（带颜色），语气次之，语速、种子是数字
function reqPills(r, { model = true, src } = {}) {
  const m = M(r.model), p = [];
  if (model && m) p.push(`<span class="pl pl-m" title="${esc(m.name)}">${mIcon(m, 12)}${esc(mName(m))}</span>`);
  if (r.instructions) p.push(`<span class="pl ${m?.caps.design ? 'pl-d' : 'pl-i'}" title="${m?.caps.design ? '声音描述' : '语气'}：${esc(r.instructions)}">${esc(trunc(r.instructions, 12))}</span>`);
  if (r.speed && r.speed !== 1) p.push(`<span class="pl pl-n" title="语速">${r.speed}×</span>`);
  if (r.seed != null) p.push(`<span class="pl pl-n" title="种子">种子 ${r.seed}</span>`);
  if (src && src !== 'webui') p.push(`<span class="pl pl-s">${src === 'cli' ? '命令行' : src === 'api' || src === 'openai' ? 'API' : esc(src)}</span>`);
  return p.join('');
}
function renderTracks() {
  const el = $('#tkList'); if (!el) return;
  const cs = S.ws.cands; $('#tkN').textContent = cs.length > 1 ? cs.length : '';
  el.innerHTML = cs.map(trackHtml).join('') + (cs.length === 1 ? `<button class="tk-add" type="button" data-addv>${ic('plus', 16)}<span><b>添加声音来对比</b>同一段文字，几个音色或模型并排听；新声音沿用当前的语气、语速和种子</span></button>` : '');
  $$('canvas.wave', el).forEach(cv => drawWave(cv, cv.dataset.url));
}
function trackHtml(c) {
  const m = M(c.model), r = candReq(c), res = S.res[rkey(r)], on = c.id === S.ws.cur, rec = res?.rec, last = !rec && c.last;
  const rr = rec && (histRec(rec.id) || rec), show = rec || last, busy = res?.busy;
  const st = !usable(m) ? `<span class="tk-st warn">${m.provider === 'local' ? '模型还没下载' : `${esc(pvName(m.provider))} 还没连接`}</span>`
    : needsDesc(c) ? '<span class="tk-st warn">先在右侧写声音描述</span>'
    : busy ? `<span class="tk-st"><span class="spin"></span>${res.cold ? '加载模型并生成…' : '生成中…'}</span>`
    : res?.queued ? '<span class="tk-st">排队中…</span>'
    : res?.err ? `<span class="tk-st bad" title="${esc(res.err)}">生成失败：${esc(res.err)}</span>`
    : rec ? '' : `<span class="tk-st">${!S.text.trim() ? '先输入文字' : last ? '文字或参数改了，再生成一次' : '还没生成'}</span>`;
  const url = show ? `/clips/${show.id}.wav` : '';
  const menu = [{ value: 'dup', label: '复制一份', sub: '改语气、语速或种子，和原来的并排比', icon: ic('dup', 15) }, { value: 'preset', label: '存为预设', icon: ic('layers', 15) },
    { value: 'code', label: '调用代码', sub: 'CLI、cURL、Python', icon: ic('code', 15) }, ...(rec ? [{ value: 'dl', label: '下载 mp3', icon: ic('download', 15) }] : []),
    ...(S.ws.cands.length > 1 ? [{ value: 'rm', label: '移除这个声音', icon: ic('x', 15), danger: true }] : [])];
  return `<div class="tk ${on ? 'on' : ''} ${last && !busy ? 'stale' : ''}" style="--m:${hue(m.id)}" data-tk="${c.id}">
    <span class="tk-l" aria-hidden="true">${tagOf(c)}</span>
    <button class="pb ${busy ? 'busy' : ''}" type="button" data-tplay ${rec || (canRun(c) && !busy && !res?.queued) ? '' : 'disabled'} ${rec ? `data-url="${url}"` : ''} aria-label="${rec ? '播放' : '生成并播放'} ${tagOf(c)}" title="${rec ? '播放' : '生成并播放'}">${busy ? '' : ic('play', 14)}</button>
    <button class="tk-who" type="button" aria-pressed="${on}" title="在右侧编辑这个声音"><b>${esc(candName(c))}</b><span class="pills">${reqPills(r)}</span></button>
    <div class="tk-res">${show && !busy ? `<canvas class="wave" data-url="${url}" data-id="${show.id}"></canvas><span class="tk-d">${show.dur.toFixed(1)}s</span>` : ''}${st}</div>
    <div class="tk-a">${rr ? asrBadge(rr) : ''}
      ${rec && regen(c) ? `<button class="btn ghost icon" type="button" data-tagain title="同样的参数再来一版${m.provider !== 'local' ? '（会再次计费）' : ''}" aria-label="再来一版">${ic('refresh', 15)}</button>` : ''}
      ${rr ? `<button class="btn ghost icon fav ${rr.star ? 'on' : ''}" type="button" data-tstar="${rr.id}" aria-pressed="${!!rr.star}" title="${rr.star ? '取消收藏' : '收藏这一版'}" aria-label="收藏">${ic('star', 15)}</button>` : ''}
      ${dd('tk-' + c.id, { menu: true, trigger: ic('more', 16), title: '更多操作', width: 240, groups: [{ items: menu }], onChange: v => trackAct(v, c) })}
    </div></div>`;
}
function trackAct(v, c) {
  const w = S.ws;
  if (v === 'dup') { const x = { ...c, id: cid() }; delete x.last; w.cands.splice(w.cands.indexOf(c) + 1, 0, x); w.cur = x.id; saveWs(); renderTracks(); renderInsp(); renderGo(); $('#insp [data-f=instr]')?.focus(); toast(`已复制为 ${tagOf(x)}：在右侧改参数，和 ${tagOf(c)} 并排比`); }
  if (v === 'preset') savePreset(candReq(c));
  if (v === 'code') openCode(c);
  if (v === 'dl') { const id = resOf(c)?.rec?.id; if (id) Object.assign(document.createElement('a'), { href: `/clips/${id}.mp3`, download: `vox-${id}.mp3` }).click(); }
  if (v === 'rm') { const i = w.cands.indexOf(c); w.cands.splice(i, 1); if (w.cur === c.id) w.cur = (w.cands[i] || w.cands[i - 1]).id; saveWs(); renderTracks(); renderInsp(); renderGo(); }
}
async function starRec(id) {
  const h = histRec(id); if (!h) return;
  h.star = !h.star; renderTracks(); renderHist();
  try { await api('/api/history/update', { id, star: h.star }); } catch (e) { h.star = !h.star; renderTracks(); renderHist(); toast(e.message, 4000); }
}

/* ---------- 右侧：选中声音的参数 ---------- */
function renderInsp() {
  const p = $('#insp'); if (!p) return;
  const c = cur(), m = M(c.model), has = k => m.params.includes(k), cp = m.caps, n = S.ws.cands.length;
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'builtin'), cl = cp.clone ? S.clones : [], curClone = cl.find(x => 'clone:' + x.id === c.voice);
  const presets = S.voices.filter(v => v.kind === 'preset');
  const ex = m.instr_examples || (cp.design ? S.cat.design : S.cat.instructions), exShown = S.exAll || ex.length <= EX_N + 1 ? ex : ex.slice(0, EX_N);
  const models = S.models.filter(x => isTTS(x) && (x.mine || x.id === m.id));
  const remote = curClone && m.provider !== 'local' && m.clone?.mode !== 'inline' && !(curClone.remote || {})[m.clone?.per_model ? m.id : m.provider];
  const y = $('.insp-b', p)?.scrollTop;
  p.style.setProperty('--m', hue(m.id));
  p.innerHTML = `
    <div class="insp-h"><span class="tk-l">${tagOf(c)}</span><div class="insp-t"><b>${esc(candName(c))}</b><span>${esc(mName(m))}</span></div>
      ${presets.length ? dd('pPreset', { menu: true, cls: 'btn ghost sm', trigger: `${ic('layers', 14)}载入预设`, title: '用一个预设替换这个声音的全部参数', width: 300,
        groups: [{ items: presets.map(v => ({ value: v.ref, label: v.name, sub: [mName(M(v.model)), v.request?.instructions].filter(Boolean).join(' · ') })) }],
        onChange: ref => { const v = S.voices.find(x => x.ref === ref); if (!v) return; Object.assign(c, newCand(v.request), { id: c.id, last: c.last }); saveWs(); renderInsp(); wsRefresh(); toast(`已载入预设「${v.name}」`); } }) : ''}</div>
    <div class="insp-b">
      <div class="field"><span class="lbl">模型</span>
        ${dd('pModel', { value: m.id, label: '模型', width: 360, groups: modelGroups(models), onChange: id => { S.exAll = false; Object.assign(c, newCand({ model: id }, c), { id: c.id, last: c.last }); saveWs(); renderInsp(); wsRefresh(); } })}
        ${usable(m) ? '' : m.provider !== 'local' ? `<p class="warn-t">${esc(pvName(m.provider))} 还没连接。<a href="#/models/${m.provider}">去连接</a>，或运行 <code>vox keys set ${esc(m.key_env)}</code></p>` : `<p class="warn-t">模型还没下载。<a href="#/models/local">去下载</a>，或运行 <code>vox models add ${esc(short(m))}</code></p>`}
        ${m.price && m.provider !== 'local' ? `<p class="note">计费 ${priceText(m)}</p>` : ''}</div>
      ${has('voice') ? `<div class="field"><span class="lbl">音色</span>
        ${vs.length || cl.length ? `<div class="vrow">${dd('pVoice', { value: c.voice, label: '音色', width: 320, groups: [
          ...(vs.length ? [{ label: cl.length ? '预置音色' : '', items: vs.map(v => ({ value: v.voice, label: v.name, sub: v.description, tags: [v.gender && [`${v.gender}声`, 'mute'], v.lang && [langName(v.lang), 'mute']].filter(Boolean), text: v.voice })) }] : []),
          ...(cl.length ? [{ label: '克隆音色', items: cl.map(x => ({ value: 'clone:' + x.id, label: x.name, sub: x.text, tags: [['克隆', 'clone'], [`${Math.round(x.duration)} 秒`, 'mute']] })) }] : [])],
          onChange: v => { c.voice = v; saveWs(); renderInsp(); wsRefresh(); } })}
          <button class="pb" type="button" id="pPreview" ${usable(m) || curClone ? '' : 'disabled'} title="${curClone ? '播放原始录音' : '试听这个音色的样本'}" aria-label="试听">${ic('play', 13)}</button></div>
          ${remote ? `<p class="note">第一次用会把录音上传给 ${esc(pvName(m.provider))}${m.clone?.fee ? `，${esc(m.clone.fee)}` : ''}</p>` : ''}`
        : `<p class="warn-t">${cp.clone ? '这个模型只用克隆音色，还没有。<a href="#/voices/clone">去克隆一个</a>' : '没有可用的音色'}</p>`}</div>` : ''}
      ${has('instructions') ? `<div class="field"><span class="lbl">${cp.design ? '声音描述' : '语气'}${cp.design ? '<span class="t t-warn">必填</span>' : ''}</span>
        <textarea class="in" data-f="instr" rows="2" placeholder="${cp.design ? '例如：三十岁左右的男声，温和真诚' : m.instr_enum ? '只能选下面的情绪之一' : m.provider === 'inworld' ? '必须用英文，例如 speak warmly and slowly' : '留空是自然语气，例如：轻快友好'}">${esc(c.instructions || '')}</textarea>
        <div class="chips sm">${exShown.map(t => `<button type="button" class="chip ${t === c.instructions ? 'on' : ''}" data-ex="${esc(t)}" title="${esc(t)}">${esc(trunc(t, 12))}</button>`).join('')}${exShown.length < ex.length ? `<button type="button" class="chip more-chip" id="exMore">更多 ${ex.length - exShown.length}</button>` : ''}</div></div>` : ''}
      <div class="field"><span class="lbl">语速<span class="val" id="vSpeed">${Number(c.speed).toFixed(2)}×</span></span>
        <input type="range" id="pSpeed" min="0.5" max="2" step="0.05" value="${c.speed}" aria-label="语速" title="双击恢复 1.00×"></div>
      ${n > 1 && !cp.design ? `<button class="linkbtn sync" type="button" id="syncAll">把语气和语速同步到其他 ${n - 1} 个声音</button>` : ''}
      ${has('seed') ? `<div class="field"><span class="lbl">种子</span>
        <div class="seedrow"><div class="seg"><button type="button" data-sm="random" class="${c.seedMode !== 'fixed' ? 'on' : ''}">每次随机</button><button type="button" data-sm="fixed" class="${c.seedMode === 'fixed' ? 'on' : ''}">固定</button></div>
        ${c.seedMode === 'fixed' ? `<input class="in mono" type="number" id="pSeed" value="${c.seed}" min="0" aria-label="种子"><button class="btn ghost icon" type="button" id="reseed" title="换一个种子" aria-label="换一个种子">${ic('dice', 15)}</button>` : ''}</div>
        <p class="note">${c.seedMode === 'fixed' ? '参数和种子不变，就是同一版声音。' : '每次生成都换一版；满意了再固定它用的种子。'}</p></div>` : ''}
      ${has('lang') || has('temperature') ? `<details class="adv" ${S.advOpen ? 'open' : ''}><summary>更多设置</summary>
        ${has('lang') ? `<div class="field"><span class="lbl">语言</span>${dd('pLang', { value: c.lang, label: '语言', groups: [{ items: LANGS.map(l => ({ value: l, label: l === 'auto' ? '自动' : langName({ chinese: 'zh', english: 'en', japanese: 'ja', korean: 'ko', german: 'de', french: 'fr', russian: 'ru', portuguese: 'pt', spanish: 'es', italian: 'it' }[l]) || l, sub: l })) }], onChange: v => { c.lang = v; saveWs(); renderInsp(); wsRefresh(); } })}</div>` : ''}
        ${has('temperature') ? [['temperature', 0.1, 1.5, 0.05], ['top_p', 0.1, 1, 0.05], ['top_k', 1, 100, 1], ['repetition_penalty', 1, 1.5, 0.01]].map(([k, a, b, st]) => `<div class="field"><span class="lbl mono-l">${k}<span class="val" data-v="${k}">${c[k]}</span></span><input type="range" data-gen="${k}" min="${a}" max="${b}" step="${st}" value="${c[k]}" aria-label="${k}"></div>`).join('') + '<button class="btn ghost sm" type="button" id="genReset">恢复默认采样参数</button>' : ''}
      </details>` : ''}
    </div>
    <div class="insp-f"><button class="btn" type="button" id="pSave">${ic('layers', 14)}存为预设</button><button class="btn ghost" type="button" id="pCode">${ic('code', 14)}调用代码</button></div>`;
  if (y) $('.insp-b', p).scrollTop = y;
  const upd = () => { saveWs(); wsRefresh(); }, redraw = () => { saveWs(); renderInsp(); wsRefresh(); };
  const pp = $('#pPreview', p); if (pp) pp.onclick = () => curClone ? playOrig(curClone.id) : playSample(`${short(m)}:${c.voice}`, pp);
  const pi = $('[data-f=instr]', p);
  if (pi) onText(pi, () => { c.instructions = pi.value; $$('[data-ex]', p).forEach(b => b.classList.toggle('on', b.dataset.ex === c.instructions)); $('.insp-t b', p).textContent = candName(c); upd(); }, 150);
  $$('[data-ex]', p).forEach(b => b.onclick = () => { c.instructions = c.instructions === b.dataset.ex ? '' : b.dataset.ex; pi.value = c.instructions; $$('[data-ex]', p).forEach(x => x.classList.toggle('on', x.dataset.ex === c.instructions)); upd(); });
  const em = $('#exMore', p); if (em) em.onclick = () => { S.exAll = true; redraw(); };
  const sp = $('#pSpeed', p);
  sp.oninput = () => { $('#vSpeed', p).textContent = (+sp.value).toFixed(2) + '×'; };
  sp.onchange = () => { c.speed = +sp.value; upd(); };
  sp.ondblclick = () => { c.speed = 1; sp.value = 1; $('#vSpeed', p).textContent = '1.00×'; upd(); };
  const sy = $('#syncAll', p); if (sy) sy.onclick = () => {
    S.ws.cands.forEach(x => { if (x === c || M(x.model).caps.design) return; if (M(x.model).params.includes('instructions')) x.instructions = c.instructions; x.speed = c.speed; });
    upd(); toast(`其他声音都改为${c.instructions ? `「${c.instructions}」` : '自然语气'}、${Number(c.speed).toFixed(2)}×`);
  };
  $$('[data-sm]', p).forEach(b => b.onclick = () => {
    // 固定时默认用最近一版实际用的种子：听到满意的再固定，正好留住它
    if (b.dataset.sm === 'fixed' && c.seedMode !== 'fixed') { const s = resOf(c)?.rec?.request?.seed ?? c.last?.request?.seed; if (s != null) c.seed = s; }
    c.seedMode = b.dataset.sm; redraw();
  });
  const ps = $('#pSeed', p); if (ps) onText(ps, () => { c.seed = +ps.value; upd(); }, 200);
  const rs = $('#reseed', p); if (rs) rs.onclick = () => { c.seed = Math.floor(Math.random() * 1e6); redraw(); };
  const adv = $('details.adv', p); if (adv) adv.ontoggle = () => S.advOpen = adv.open;
  $$('[data-gen]', p).forEach(r => { r.oninput = () => { $(`[data-v="${r.dataset.gen}"]`, p).textContent = r.value; }; r.onchange = () => { c[r.dataset.gen] = +r.value; upd(); }; });
  const gr = $('#genReset', p); if (gr) gr.onclick = () => { Object.assign(c, GEN_DEFAULT); redraw(); };
  $('#pSave', p).onclick = () => savePreset(candReq(c));
  $('#pCode', p).onclick = () => openCode(c);
}

/* ---------- 调用代码（面板） ---------- */
function openCode(c) {
  const r = reqOf(c, S.text.trim() || '要合成的文字'), tabs = { cli: 'CLI', curl: 'cURL', python: 'Python' };
  const draw = () => {
    const box = openSheet(`${sheetHead('调用代码', `声音 ${tagOf(c)} · ${esc(candName(c))}：同样的请求，在终端或代码里这样写`)}
      <div class="sh-b"><div class="tabs" role="tablist">${Object.entries(tabs).map(([k, t]) => `<button type="button" role="tab" data-ck="${k}" class="${S.equiv === k ? 'on' : ''}" aria-selected="${S.equiv === k}">${t}</button>`).join('')}</div>
        <pre class="code">${esc(cmdOf(r, S.equiv))}</pre>
        <p class="note">参数名在命令行、HTTP API 和网页里一致：<code>model</code> <code>voice</code> <code>instructions</code> <code>speed</code> <code>seed</code>。HTTP 接口兼容 OpenAI，Base URL 是 <code>${ORIGIN}/v1</code>。</p></div>
      <footer class="sh-f"><div class="sh-a"><span class="sp"></span><button class="btn ghost" type="button" data-shclose>关闭</button><button class="btn primary" type="button" id="cdCopy">${ic('copy', 14)}复制</button></div></footer>`);
    $$('[data-shclose]', box).forEach(b => b.onclick = closeSheet);
    $$('[data-ck]', box).forEach(b => b.onclick = () => { S.equiv = b.dataset.ck; store.set('equiv', S.equiv); draw(); });
    $('#cdCopy', box).onclick = () => copy(cmdOf(r, S.equiv), '已复制，可以直接在终端或脚本里运行');
  };
  draw();
}

/* ---------- 添加声音（面板）：从预置、克隆、预设里挑，可多选 ---------- */
function openAddVoices() {
  const st = { q: '', kind: 'builtin', pick: new Map() };
  const have = new Set(S.ws.cands.map(c => `${c.model}|${c.voice || ''}`));
  const pool = k => S.voices.filter(v => v.kind === k && usable(M(v.model)));
  const kinds = [['builtin', '预置音色'], ['clone', '克隆音色'], ['preset', '预设']].filter(([k]) => k === 'builtin' || pool(k).length);
  const list = () => {
    const q = st.q.trim().toLowerCase(), vs = pool(st.kind).filter(v => !q || `${v.name} ${v.ref} ${v.description} ${v.lang} ${langName(v.lang)}`.toLowerCase().includes(q));
    const groups = st.kind === 'builtin' ? [...new Set(vs.map(v => v.model))].map(mid => ({ m: M(mid), vs: vs.filter(v => v.model === mid) })) : [{ vs }];
    return groups.map(g => `${g.m ? `<div class="pk-g">${mIcon(g.m, 13)}${mTitle(g.m)}<span class="n">${g.vs.length}</span></div>` : ''}${g.vs.slice(0, q ? 200 : 60).map(v => {
      const dup = st.kind !== 'preset' && have.has(`${v.model}|${v.voice}`), on = st.pick.has(v.ref);
      const tags = st.kind === 'clone' ? [['克隆', 'clone']] : st.kind === 'preset' ? [[mName(M(v.model)), 'mute']] : [v.gender && [`${v.gender}声`, 'mute'], v.lang && [langName(v.lang), 'mute']].filter(Boolean);
      return `<label class="pk-i ${dup ? 'dis' : ''} ${on ? 'on' : ''}" style="--m:${hue(v.model)}"><input type="checkbox" value="${esc(v.ref)}" ${dup ? 'disabled checked' : on ? 'checked' : ''}>
        <span class="pk-t"><span class="dd-r"><b>${esc(v.name)}</b>${tags.map(tagHtml).join('')}${dup ? '<span class="t t-mute">已在列表里</span>' : ''}</span><span class="dd-s">${esc(st.kind === 'clone' ? S.clones.find(x => 'clone:' + x.id === v.ref)?.text || '' : v.description || '')}</span></span>
        <button class="pb sm" type="button" data-pks="${esc(v.ref)}" data-url="${esc(v.sample.url)}" aria-label="试听 ${esc(v.name)}" title="试听样本">${ic('play', 11)}</button></label>`;
    }).join('')}${!q && g.vs.length > 60 ? `<p class="note pk-more">还有 ${g.vs.length - 60} 个，搜索查看</p>` : ''}`).join('') || '<p class="sec-empty">没有匹配的声音。</p>';
  };
  const foot = () => { const n = st.pick.size, b = $('#pkAdd', SHEET); b.disabled = !n; b.textContent = n ? `添加 ${n} 个声音` : '添加'; };
  const box = openSheet(`${sheetHead('添加声音', '新声音沿用当前选中声音的语气、语速和种子，比较时只差音色或模型；预设会带上它自己的全部参数。')}
    <div class="pk-bar"><div class="tabs" role="tablist">${kinds.map(([k, t]) => `<button type="button" role="tab" data-pkk="${k}" class="${st.kind === k ? 'on' : ''}">${t}</button>`).join('')}</div>
      <label class="search">${ic('search', 15)}<input class="in" id="pkQ" type="search" placeholder="搜索名字、描述、语言" aria-label="搜索声音"></label></div>
    <div class="sh-b pk-list" id="pkList">${list()}</div>
    <footer class="sh-f"><div class="sh-a"><span class="note">可以多选</span><span class="sp"></span><button class="btn ghost" type="button" data-shclose>取消</button><button class="btn primary" type="button" id="pkAdd" disabled>添加</button></div></footer>`);
  const relist = () => { $('#pkList', box).innerHTML = list(); bind(); };
  const bind = () => {
    $$('#pkList input[type=checkbox]:not([disabled])', box).forEach(i => i.onchange = () => { i.checked ? st.pick.set(i.value, st.kind) : st.pick.delete(i.value); i.closest('.pk-i').classList.toggle('on', i.checked); foot(); });
    $$('[data-pks]', box).forEach(b => b.onclick = e => { e.preventDefault(); playSample(b.dataset.pks, b); });
  };
  bind();
  $$('[data-shclose]', box).forEach(b => b.onclick = closeSheet);
  $$('[data-pkk]', box).forEach(b => b.onclick = () => { st.kind = b.dataset.pkk; $$('[data-pkk]', box).forEach(x => x.classList.toggle('on', x === b)); relist(); });
  const q = $('#pkQ', box); onText(q, () => { st.q = q.value; relist(); }, 150); q.focus();
  $('#pkAdd', box).onclick = () => {
    const from = cur(), added = [];
    st.pick.forEach((k, ref) => { const v = S.voices.find(x => x.ref === ref); if (v) added.push(k === 'preset' ? newCand(v.request) : newCand({ model: v.model, voice: v.voice }, from)); });
    if (!added.length) return;
    S.ws.cands = [...S.ws.cands, ...added];
    S.ws.cur = added[0].id; saveWs(); closeSheet(); renderInsp(); wsRefresh(); toast(`已添加 ${added.length} 个声音，按「生成」一起听`);
  };
}

/* ---------- 历史：所有生成过的（网页、命令行、API） ---------- */
const when = ts => { const d = new Date(ts * 1000), today = new Date().toDateString() === d.toDateString(); return `${today ? '' : `${d.getMonth() + 1}/${d.getDate()} `}${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
function renderHist() {
  const el = $('#hist'); if (!el || S.route !== 'playground') return;
  const hs = S.hist.filter(h => !S.histStar || h.star), shown = hs.slice(0, S.histLimit), nStar = S.hist.filter(h => h.star).length;
  el.innerHTML = `<div class="sec-t"><h2>历史</h2><span class="note">网页、命令行和 API 生成的都在这里</span><span class="sp"></span>
      <div class="seg sm" role="group" aria-label="筛选历史"><button type="button" data-hs="0" class="${S.histStar ? '' : 'on'}">全部</button><button type="button" data-hs="1" class="${S.histStar ? 'on' : ''}">${ic('star', 12)}收藏${nStar ? ` ${nStar}` : ''}</button></div></div>
    ${shown.length ? `<div class="hlist">${shown.map(histRow).join('')}</div>` : `<div class="empty">${S.histStar ? '还没有收藏。听到满意的一版，点它右边的星标。' : '还没有生成过。在上面写一段文字，按「生成」。'}</div>`}
    ${hs.length > shown.length ? `<div class="more"><button class="btn" type="button" id="histMore">再显示 ${Math.min(30, hs.length - shown.length)} 条<span class="n">共 ${hs.length}</span></button></div>` : ''}`;
  $$('[data-hs]', el).forEach(b => b.onclick = () => { S.histStar = b.dataset.hs === '1'; renderHist(); });
  const hm = $('#histMore', el); if (hm) hm.onclick = () => { S.histLimit += 30; renderHist(); };
}
function histRow(h) {
  const r = h.request, menu = [{ value: 'reuse', label: '复现', sub: '文字和参数都填回，替换当前选中的声音', icon: ic('refresh', 15) }, { value: 'preset', label: '存为预设', icon: ic('layers', 15) },
    { value: 'cmd', label: '复制命令', icon: ic('code', 15) }, { value: 'dl', label: '下载 mp3', icon: ic('download', 15) }];
  return `<div class="hr" style="--m:${hue(r.model)}" data-h="${h.id}">
    <button class="pb sm" type="button" data-hplay data-url="/clips/${h.id}.wav" aria-label="播放">${ic('play', 12)}</button>
    <div class="hr-main"><div class="hr-t"><b>${esc(recName(r))}</b><span class="pills">${reqPills(r, { src: h.source })}</span></div>
      <p class="hr-x" title="${esc(r.input)}">${esc(r.input)}</p></div>
    <div class="hr-m">${asrBadge(h)}<span class="hr-d">${h.dur.toFixed(1)}s</span><time>${when(h.ts)}</time></div>
    <div class="hr-a"><button class="btn ghost sm" type="button" data-hadd title="把这一版的参数（含种子）作为新声音加入上面的列表，文字不变">${ic('plus', 13)}加入对比</button>
      <button class="btn ghost icon fav ${h.star ? 'on' : ''}" type="button" data-hstar aria-pressed="${!!h.star}" title="${h.star ? '取消收藏' : '收藏'}" aria-label="收藏">${ic('star', 15)}</button>
      ${dd('h-' + h.id, { menu: true, trigger: ic('more', 16), title: '更多操作', width: 250, groups: [{ items: menu }], onChange: v => histAct(v, h) })}</div>
    ${asrHtml(h)}</div>`;
}
function histAct(v, h) {
  const r = h.request;
  if (v === 'reuse' || v === 'add') {
    const c = v === 'reuse' ? Object.assign(cur(), newCand(r), { id: cur().id }) : newCand(r);
    if (r.seed != null) Object.assign(c, { seedMode: 'fixed', seed: r.seed });
    if (v === 'reuse') { S.text = r.input; store.set('text', S.text); $('#text').value = S.text; }
    else { S.ws.cands.push(c); S.ws.cur = c.id; }
    S.res[rkey(candReq(c))] = { rec: slim(h) }; c.last = slim(h);   // 正好是这一版：直接显示，不用重新生成
    saveWs(); renderInsp(); wsRefresh();
    scrollTo({ top: 0, behavior: 'smooth' });
    toast(v === 'reuse' ? '已复现：文字和参数（含种子）都填回了' : `已加入对比，现在有 ${S.ws.cands.length} 个声音`);
  }
  if (v === 'preset') savePreset(r);
  if (v === 'cmd') copy(cmdOf(r, 'cli'), '已复制命令');
  if (v === 'dl') Object.assign(document.createElement('a'), { href: `/clips/${h.id}.mp3`, download: `vox-${h.id}.mp3` }).click();
}

/* 读音校对：本地 ASR 转回文字，按字对齐，标出没读对的字 */
const DIG = '零一二三四五六七八九';
const norm = s => [...String(s).toLowerCase().replace(/[0-9]/g, d => DIG[d])].filter(c => /[一-鿿a-z]/.test(c));
function asrDiff(want, got) {
  const a = norm(want), b = norm(got), n = a.length, m = b.length, dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const hit = Array(n).fill(false); let i = 0, j = 0;
  while (i < n && j < m) { if (a[i] === b[j]) { hit[i++] = true; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) i++; else j++; }
  return { a, hit, score: n ? dp[0][0] / n : 1 };
}
// 读音校对：结果栏里一个分数；有读错的字才展开，标出错字和识别结果
function asrBadge(h) {
  if (h._asrBusy) return '<span class="asr-b">读音校对中…</span>';
  if (!h.asr) return S.status?.asr ? `<button class="linkbtn" type="button" data-asr title="用本地识别模型把音频转回文字，标出读错的字">校对读音</button>` : '';
  const { score } = asrDiff(h.request.input, h.asr), cls = score > .97 ? 'ok' : score > .85 ? 'warn' : 'bad';
  return `<span class="asr-b ${cls}" title="识别结果：${esc(h.asr)}">${cls === 'ok' ? ic('check', 12) : ''}读音 ${Math.round(score * 100)}%</span>`;
}
function asrHtml(h) {
  if (!h.asr || h._asrBusy) return '';
  const { a, hit } = asrDiff(h.request.input, h.asr);
  if (hit.every(Boolean)) return '';
  return `<div class="asr"><p>${a.map((c, i) => hit[i] ? esc(c) : `<span class="x">${esc(c)}</span>`).join('')}</p><small>识别结果：${esc(h.asr)}</small></div>`;
}
async function runAsr(id) {
  const h = histRec(id); if (!h || h._asrBusy) return;
  h._asrBusy = true; renderTracks(); renderHist();
  try { const r = await api('/api/asr', { id }); h.asr = r.text; } catch (e) { toast(`读音校对失败：${e.message}`, 5000); }
  h._asrBusy = false; renderTracks(); renderHist();
}

/* ============ 模型：左侧 Provider，右侧它的模型 ============ */
// 「能不能用」是系统事实（本地下没下载、云端连没连上），不给开关；「已添加」= 能用的模型里留下的那些，音色库、试音台和转写只显示这些。
const GROUPS = [['local', '本地'], ['aggregator', '聚合'], ['cloud', '云端'], ['custom', '自定义']];
const pGroup = p => p.kind === 'local' ? 'local' : p.custom ? 'custom' : p.region === '聚合' ? 'aggregator' : 'cloud';
const ago = t => { const d = Date.now() / 1000 - t; return d < 60 ? '刚刚' : d < 3600 ? `${Math.floor(d / 60)} 分钟前` : d < 86400 ? `${Math.floor(d / 3600)} 小时前` : `${Math.floor(d / 86400)} 天前`; };
const fmtN = n => n >= 1e4 ? `${(n / 1e4).toFixed(1).replace(/\.0$/, '')} 万` : n.toLocaleString();
S.disc = {}; S.mq = {}; S.keyEdit = null;

function pageModels(main) {
  const ps = S.providers, sub = S.sub === 'mine' || S.sub === 'new' || PV(S.sub) ? S.sub : 'mine';
  if (S.sub !== sub) history.replaceState(null, '', `#/models/${sub}`);
  S.sub = sub;
  const item = p => `<a class="pv ${p.id === sub ? 'on' : ''}" href="#/models/${p.id}" ${p.id === sub ? 'aria-current="page"' : ''}>${pIcon(p.id, 18)}<span class="pv-n">${esc(p.name)}</span>
    ${p.mine ? `<span class="pv-c">${p.mine}</span>` : ''}<i class="st ${p.connected ? 'on' : ''}" title="${p.kind === 'local' ? '本机' : p.connected ? '已连接' : '未连接'}"></i></a>`;
  main.innerHTML = `
    <div class="head"><div><h1>模型</h1><p>已添加的模型会出现在音色库、试音台和转写里。本地模型下载后自动添加；云端模型要先连接 Provider，再挑需要的添加。</p></div>
      <button class="cli" type="button" data-copy="vox models">vox models</button></div>
    <div class="mp">
      <nav class="mp-side" aria-label="Provider">
        <a class="pv ${sub === 'mine' ? 'on' : ''}" href="#/models/mine" ${sub === 'mine' ? 'aria-current="page"' : ''}>${ic('layers', 18)}<span class="pv-n">已添加</span><span class="pv-c">${mine().length}</span></a>
        ${GROUPS.map(([g, t]) => { const list = ps.filter(p => pGroup(p) === g);
          return list.length || g === 'custom' ? `<div class="mp-g"><span>${t}</span>${g === 'cloud' ? `<span>${list.filter(p => p.connected).length}/${list.length} 已连接</span>` : ''}</div>${list.map(item).join('')}` : ''; }).join('')}
        <a class="pv add ${sub === 'new' ? 'on' : ''}" href="#/models/new">${ic('plus', 18)}<span class="pv-n">添加 Provider</span></a>
        <div class="mp-foot" id="regInfo"></div>
      </nav>
      <section class="mp-main" id="pd"></section>
    </div>`;
  $('[data-copy]', main).onclick = e => copy(e.currentTarget.dataset.copy, '已复制命令');
  const pd = $('#pd', main);
  sub === 'mine' ? renderMine(pd) : sub === 'new' ? renderProviderForm(pd) : S.editProv === sub ? renderProviderForm(pd, PV(sub)) : renderProvider(pd);
  api('/api/registry').then(r => {
    const el = $('#regInfo', main); if (!el) return;
    el.innerHTML = `<span title="模型元数据（能力、价格、音色）来自注册表；vox models update 拉新版">注册表 ${esc(r.updated)} · ${r.from === 'builtin' ? '内置' : '已更新'}</span>`;
  }).catch(() => {});
  if (S.models.some(m => m.status === 'downloading')) pollPull(main);
}
function renderMine(el) {
  const my = mine(), pids = [...new Set(my.map(m => m.provider))], nl = my.filter(m => m.provider === 'local').length;
  el.innerHTML = `
    <div class="pd-h"><span class="pd-ic">${ic('layers', 22)}</span><div><h2>已添加的模型</h2><p>${my.length ? `共 ${my.length} 个，本地 ${nl} 个、云端 ${my.length - nl} 个，都可以直接用。` : '还没有添加模型。'}</p></div></div>
    ${my.length ? pids.map(pid => `<section class="sec"><div class="sec-h"><h3>${pIcon(pid, 16)}${esc(PV(pid)?.name || pid)}</h3><span class="n">${my.filter(m => m.provider === pid).length}</span><span class="sp"></span>
        <a class="btn ghost sm" href="#/models/${pid}">管理${ic('arrow', 13)}</a></div><div class="mlist">${my.filter(m => m.provider === pid).map(modelRow).join('')}</div></section>`).join('')
      : `<div class="empty"><b>从这里开始</b>下载一个<a href="#/models/local">本地模型</a>，下载后完全离线运行；或者连接一家云端 Provider，比如 <a href="#/models/openrouter">OpenRouter</a>，一个 Key 就能用它的全部 TTS 模型。</div>`}`;
  bindRows(el);
}
function renderProvider(el) {
  const p = PV(S.sub), local = p.kind === 'local', ms = S.models.filter(m => m.provider === p.id);
  const my = ms.filter(m => m.mine), avail = ms.filter(m => !m.mine), rec = ms.filter(m => m.recommended).length;
  const d = p.discover, st = S.disc[p.id], busy = st === 'loading', err = st && st !== 'loading' ? st : null;
  const q = (S.mq[p.id] || '').trim().toLowerCase(), shown = q ? avail.filter(m => `${m.id} ${m.name}`.toLowerCase().includes(q)) : avail;
  const canFetch = d && (d.public || p.connected), src = local ? 'HuggingFace' : p.name;
  const note = !d ? '这家没有公开的模型列表接口，列表来自 vox 注册表' : d.fetched ? `${ago(d.fetched)}从 ${esc(src)} 查询` : canFetch ? `可以从 ${esc(src)} 查询完整列表` : '连接后可以在线查询完整列表';
  el.innerHTML = `
    <div class="pd-h">${pIcon(p.id, 32)}<div><h2>${esc(p.name)}</h2><p>${esc(p.about || `${p.region || ''}云端 TTS`)}${local && S.status?.models ? ` · 存放在 <code class="mono">${esc(S.status.models.replace(/^\/Users\/[^/]+/, '~'))}</code>` : ''}</p></div><span class="sp"></span>
      ${p.docs ? `<a class="lnk" href="${esc(p.docs)}" target="_blank" rel="noopener">API 文档${ic('ext', 13)}</a>` : ''}
      ${p.custom ? `<button class="btn sm" type="button" id="pEdit">${ic('edit', 14)}编辑</button><button class="btn ghost sm danger" type="button" id="pDel">删除</button>` : ''}</div>
    ${local ? '' : p.credentials.length ? connHtml(p) : `<section class="sec conn"><div class="sec-h"><h3>连接</h3><span class="pill loaded">${ic('check', 12)}不需要 Key</span><span class="sp"></span><span class="note">${esc(p.base_url || '')}</span></div></section>`}
    <section class="sec"><div class="sec-h"><h3>已添加</h3><span class="n">${my.length}</span></div>
      ${my.length ? `<div class="mlist">${my.map(modelRow).join('')}</div>` : `<p class="sec-empty">${local ? '还没有下载模型。从下面挑一个，下载后完全离线运行。' : !p.connected ? (rec ? `连接后，默认加上 ${rec} 个 vox 核对过的模型；更多模型在下面添加。` : '连接后，从下面添加想用的模型。') : '还没有添加模型。从下面添加。'}</p>`}
    </section>
    <section class="sec"><div class="sec-h"><h3>${local ? '可下载' : '可添加'}</h3><span class="n">${avail.length}</span><span class="sp"></span><span class="note">${note}</span>
      ${d ? `<button class="btn sm" type="button" id="dFetch" ${canFetch && !busy ? '' : 'disabled'} ${canFetch ? '' : 'title="先连接（填 Key）"'}>${ic('refresh', 14, busy ? 'spin' : '')}${busy ? '查询中' : d.fetched ? '刷新' : '在线查询'}</button>` : ''}</div>
      ${err ? `<div class="err">${esc(err)}</div>` : ''}
      ${avail.length > 8 ? `<label class="search">${ic('search', 15)}<input class="in" id="mq" placeholder="筛选 ${avail.length} 个模型" value="${esc(S.mq[p.id] || '')}" aria-label="筛选模型"></label>` : ''}
      ${shown.length ? `<div class="mlist">${shown.map(modelRow).join('')}</div>` : `<p class="sec-empty">${busy ? '正在查询…' : q ? '没有匹配的模型。' : avail.length ? '' : '都已添加。'}</p>`}
      ${local ? '' : `<form class="manual" id="dAdd"><span>列表里没有？</span><input class="in mono" placeholder="手动填 ${esc(p.name)} 的模型 ID" aria-label="模型 ID" spellcheck="false" autocomplete="off" ${p.connected ? '' : 'disabled'}>
        <button class="btn sm" type="submit" ${p.connected ? '' : 'disabled title="先连接（填 Key）"'}>${ic('plus', 14)}添加</button></form>`}
    </section>`;
  bindProvider(el, p);
  if (d && d.public && !d.fetched && !st) fetchModels(el, p);   // 公开列表：第一次打开时自动查
}
/* ---------- 自定义 Provider：添加 / 编辑 ---------- */
// 目前一种类型：OpenAI 兼容（POST {Base URL}/audio/speech），覆盖自建服务、代理和多数新厂商。
const PROVIDER_PRESETS = [
  { label: 'Kokoro-FastAPI（本机）', id: 'kokoro-fastapi', config: { name: 'Kokoro-FastAPI', base_url: 'http://127.0.0.1:8880/v1', auth: false, instructions: 'none' } },
  { label: '另一台 vox', id: 'other-vox', config: { name: '另一台 vox', base_url: 'http://127.0.0.1:8765/v1', auth: false, instructions: 'instructions' } },
  { label: 'OpenAI 兼容代理', id: 'openai-proxy', config: { name: 'OpenAI 代理', base_url: 'https://', auth: true, instructions: 'instructions', model_filter: 'tts' } },
];
const slug = t => String(t || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32);
function renderProviderForm(el, p) {
  const editing = !!p, c = { auth: true, instructions: 'instructions', native_speed: true, fetch_voices: true, ...(p?.config || S.pform || {}) };
  const pid = editing ? p.id : (S.pformId || '');
  el.innerHTML = `
    <div class="pd-h"><span class="pd-ic">${editing ? pIcon(p.id, 28) : ic('plus', 22)}</span><div><h2>${editing ? `编辑 ${esc(p.name)}` : '添加 Provider'}</h2>
      <p>接入任何 OpenAI 兼容的语音服务：本机自建的（Kokoro-FastAPI、LocalAI…）、代理、或 vox 还没收录的厂商。vox 会调用 <code class="mono">POST {Base URL}/audio/speech</code>。</p></div></div>
    ${editing ? '' : `<div class="presets"><span class="note">快速填写</span>${PROVIDER_PRESETS.map((x, i) => `<button class="chip" type="button" data-preset="${i}">${esc(x.label)}</button>`).join('')}</div>`}
    <form class="sec pform" id="pform" autocomplete="off">
      <div class="pf-grid">
        <div class="field"><div class="lbl"><span>名称</span></div><input class="in" name="name" value="${esc(c.name || '')}" placeholder="例如：Kokoro 本机" required></div>
        <div class="field"><div class="lbl"><span>ID</span><span class="key">命令行和模型 ID 里用</span></div><input class="in mono" name="id" value="${esc(pid)}" placeholder="my-kokoro" ${editing ? 'disabled' : ''} pattern="[a-z0-9][a-z0-9-]{1,31}" required></div>
        <div class="field"><div class="lbl"><span>类型</span></div><input type="hidden" name="type" value="openai">${dd('pfType', { value: 'openai', label: '类型', groups: [{ items: [{ value: 'openai', label: 'OpenAI 兼容', sub: 'POST {Base URL}/audio/speech' }] }] })}</div>
        <div class="field wide"><div class="lbl"><span>Base URL</span><span class="key">到 /v1 为止</span></div><input class="in mono" name="base_url" value="${esc(c.base_url || '')}" placeholder="http://127.0.0.1:8880/v1" required spellcheck="false"></div>
        <div class="field wide"><div class="lbl"><span>API Key</span></div>
          <div class="pf-key"><div class="seg" role="group" aria-label="是否需要 Key"><button type="button" data-auth="1" class="${c.auth ? 'on' : ''}">需要</button><button type="button" data-auth="0" class="${c.auth ? '' : 'on'}">不需要（本机自建常见）</button></div>
          ${c.auth ? `<input class="in mono" name="key" type="password" placeholder="${editing && p.connected ? '已保存；粘贴新值以替换' : '粘贴 Key（也可以之后再填）'}" spellcheck="false">` : ''}</div></div>
      </div>
      <details class="adv" ${editing ? 'open' : ''}><summary>兼容选项</summary>
        <div class="pf-grid">
          <div class="field"><div class="lbl"><span>情绪指令怎么传</span><span class="key">instructions</span></div>
            <input type="hidden" name="instructions" value="${esc(c.instructions)}">${dd('pfIns', { value: c.instructions, label: '情绪指令怎么传', groups: [{ items: [['instructions', 'instructions 字段', 'OpenAI 的写法'], ['instruction', 'instruction 字段', '少数厂商用单数'], ['prefix', '写进正文', '指令<|endofprompt|>正文'], ['none', '不支持', '不传情绪指令']].map(([k, t, sub]) => ({ value: k, label: t, sub })) }], onChange: v => { $('[name=instructions]', el).value = v; DD.pfIns.value = v; keep(); renderProviderForm(el, p); } })}</div>
          <div class="field"><div class="lbl"><span>模型列表只保留名字含</span><span class="key">可空</span></div><input class="in mono" name="model_filter" value="${esc(c.model_filter || '')}" placeholder="例如 tts"></div>
          <label class="pf-check"><input type="checkbox" name="native_speed" ${c.native_speed ? 'checked' : ''}> 服务支持 speed 参数（不勾则由 vox 用 ffmpeg 变速）</label>
          <label class="pf-check"><input type="checkbox" name="fetch_voices" ${c.fetch_voices ? 'checked' : ''}> 从 <code class="mono">{Base URL}/audio/voices</code> 获取音色列表</label>
          <div class="field wide"><div class="lbl"><span>手动指定音色</span><span class="key">逗号分隔，可空</span></div><input class="in mono" name="voices" value="${esc((c.voices || []).join(', '))}" placeholder="alloy, echo, nova"></div>
        </div>
      </details>
      <div class="pf-a"><button class="btn" type="button" id="pfTest">${ic('refresh', 14)}测试连接</button><span class="note" id="pfRes"></span><span class="sp"></span>
        <a class="btn ghost" href="#/models/${editing ? p.id : 'mine'}" id="pfCancel">取消</a><button class="btn primary" type="submit">${editing ? '保存' : '添加'}</button></div>
    </form>`;
  const f = $('#pform', el), fe = n => f.elements.namedItem(n), val = () => {
    const d = Object.fromEntries(new FormData(f));
    return { id: editing ? p.id : (d.id || '').trim(), key: d.key || null,
      config: { name: d.name.trim(), type: d.type, base_url: d.base_url.trim(), auth: c.auth, instructions: d.instructions, model_filter: d.model_filter.trim(),
        native_speed: !!fe('native_speed').checked, fetch_voices: !!fe('fetch_voices').checked, voices: d.voices.split(',').map(x => x.trim()).filter(Boolean) } };
  };
  const keep = () => { const v = val(); S.pform = v.config; S.pformId = v.id; };
  const fid = fe('id'), fname = fe('name');
  onText(fname, () => { if (!editing && (!fid.value || fid.dataset.auto)) { fid.value = slug(fname.value) || fid.value; fid.dataset.auto = '1'; } });
  fid.oninput = () => { delete fid.dataset.auto; };
  $$('[data-auth]', f).forEach(b => b.onclick = () => { keep(); S.pform.auth = b.dataset.auth === '1'; c.auth = S.pform.auth; renderProviderForm(el, p); });
  $$('[data-preset]', el).forEach(b => b.onclick = () => { const x = PROVIDER_PRESETS[+b.dataset.preset]; S.pform = { ...x.config }; S.pformId = x.id; renderProviderForm(el); $('[name=base_url]', el).focus(); });
  $('#pfCancel', el).onclick = () => { S.pform = null; S.pformId = ''; S.editProv = null; };
  $('#pfTest', el).onclick = async () => {
    const v = val(), res = $('#pfRes', el), b = $('#pfTest', el); b.disabled = true; res.className = 'note'; res.textContent = '连接中…';
    try {
      const r = await api('/api/providers/test', editing && !v.key && p.connected ? { id: p.id } : { config: v.config, key: v.key });
      res.className = r.ok ? 'note ok' : 'err';
      res.textContent = r.ok ? `连得上：${r.models.length} 个模型${r.voices != null ? `，${r.voices} 个音色` : '；没有音色列表接口，可以手动填音色'}${r.models.length ? `（${r.models.slice(0, 3).join('、')}${r.models.length > 3 ? '…' : ''}）` : ''}` : r.error;
    } catch (e) { res.className = 'err'; res.textContent = e.message; }
    b.disabled = false;
  };
  f.onsubmit = async e => {
    e.preventDefault(); const v = val();
    try {
      const r = await api('/api/providers/add', { id: v.id, config: v.config, key: v.key, overwrite: editing });
      S.pform = null; S.pformId = ''; S.editProv = null;
      await afterModels();
      toast(`${editing ? '已保存' : '已添加'} ${v.config.name || v.id}${r.found != null ? `，查到 ${r.found} 个模型` : r.error ? '；模型列表没查到，可以手动添加模型 ID' : ''}`, 4000);
      location.hash = `#/models/${r.provider}`; if (S.sub === r.provider) rerender();
    } catch (err) { toast(err.message, 5000); }
  };
}

function connHtml(p) {
  const env = p.credentials[0]?.env;
  return `<section class="sec conn"><div class="sec-h"><h3>连接</h3>${p.connected ? `<span class="pill loaded">${ic('check', 12)}已连接</span>` : '<span class="pill needs_key">未连接</span>'}<span class="sp"></span>
      ${p.console ? `<a class="lnk" href="${esc(p.console)}" target="_blank" rel="noopener">申请 Key${ic('ext', 13)}</a>` : ''}</div>
    ${p.credentials.map(c => keyField(p, c, false)).join('')}
    ${p.optional.length ? `<details class="adv"><summary>可选设置</summary>${p.optional.map(c => keyField(p, c, true)).join('')}</details>` : ''}
    <details class="adv"><summary>Key 存在哪里？</summary><div class="keynote">两种方式都行，<b>环境变量优先</b>：
      <ul><li><b>在这里填</b>：保存到本机 <code>~/.config/vox/credentials.json</code>（权限 600），立即生效。</li>
      <li><b>环境变量</b>：如 <code>export ${esc(env)}=…</code>，适合终端、脚本、Agent 和 CI，会覆盖这里保存的值。</li></ul>
      Key 不会通过 API 返回，也不写进日志，页面只显示末 4 位。命令行：<code>vox keys set ${esc(env)}</code></div></details>
  </section>`;
}
function keyField(p, c, opt) {
  const editing = S.keyEdit === c.env || !c.configured;
  return `<div class="kf">
    <div class="lbl"><span>${esc(c.label)}</span><span class="key">${esc(c.env)}</span></div>
    ${c.configured && !editing ? `<div class="kset"><code class="mono">••••${esc(c.last4 || '')}</code><span class="note">来自${c.source === 'env' ? '环境变量，在终端里修改' : '配置文件'}</span><span class="sp"></span>
      ${c.source === 'file' ? `<button class="btn ghost sm" type="button" data-keyedit="${esc(c.env)}">更换</button><button class="btn ghost sm danger" type="button" data-delkey="${esc(c.env)}">删除</button>` : ''}</div>` : ''}
    ${editing && c.source !== 'env' ? `<form data-env="${esc(c.env)}" class="kform"><input class="in mono" type="password" autocomplete="off" spellcheck="false" placeholder="${c.configured ? '粘贴新的值' : opt ? '可选' : '粘贴 Key'}" aria-label="${esc(c.env)}">
      <button class="btn ${opt ? '' : 'primary'}" type="submit">${opt ? '保存' : c.configured ? '保存' : '连接'}</button>${c.configured ? '<button class="btn ghost" type="button" data-keycancel>取消</button>' : ''}</form>` : ''}</div>`;
}
function statusPill(m) {
  return m.status === 'loaded' ? '<span class="t t-ok" title="已在内存中，生成不用等加载">已加载</span>' : m.status === 'downloading' ? tagHtml(['下载中', 'warn']) : '';
}
function modelRow(m) {
  const cloud = m.provider !== 'local';
  const params = m.params_b ? (m.params_b >= 1 ? `${m.params_b}B` : `${Math.round(m.params_b * 1000)}M`) : '';
  const facts = cloud ? [priceText(m) || (m.inferred ? '价格见官网' : ''), m.voice_count ? `${m.voice_count} 个音色` : '']
    : [[params, m.quant].filter(Boolean).join(' · '), m.size_gb ? `${m.size_gb} GB` : '', m.voice_count ? `${m.voice_count} 个音色` : '', m.downloads ? `${fmtN(m.downloads)} 次下载` : ''];
  const tags = [isTTS(m) ? '' : tagHtml(['语音识别', 'mute']), ...(m.tags || []).map(t => tagHtml([t, 'mute'])), m.inferred ? '<span class="t t-warn" title="vox 注册表里没有这个模型：请求格式与能力按同一家已核对的模型推断">能力推断</span>' : '', m.source === 'custom' && cloud ? tagHtml(['手动添加', 'mute']) : ''].join('');
  return `<div class="mrow ${m.mine ? 'is-mine' : ''}" style="--m:${hue(m.id)}">
    <div class="mr-main">
      <div class="mr-t"><b>${mTitle(m)}</b>${statusPill(m)}${mTags(m, { status: false }).map(tagHtml).join('')}${tags}</div>
      <div class="mr-s"><button class="idc" type="button" data-copyid="${esc(m.id)}" title="复制模型 ID">${esc(m.id)}${ic('copy', 12)}</button>${facts.filter(Boolean).map(f => `<span>${f}</span>`).join('')}</div>
      ${m.about ? `<p class="mr-d">${esc(m.about)}</p>` : ''}
      ${capsHtml(m)}
    </div>
    <div class="mr-a">${rowActions(m)}</div></div>`;
}
function rowActions(m) {
  const cloud = m.provider !== 'local', id = esc(m.id), p = PV(m.provider);
  if (m.status === 'downloading') return `<div class="dl"><span class="note" data-prog="${id}">下载中…</span><div class="bar"><i data-bar="${id}"></i></div></div>`;
  if (m.mine) {
    const tryBtn = isTTS(m) ? `<a class="btn sm" href="#/playground" data-trym="${id}">试音${ic('arrow', 13)}</a>` : `<a class="btn sm" href="#/transcribe" data-tryt="${id}">转写${ic('arrow', 13)}</a>`;
    if (cloud) return `<button class="btn ghost sm" type="button" data-rm="${id}" title="从已添加里移除，不影响账号">移除</button>${tryBtn}`;
    return `${m.status === 'loaded' ? `<button class="btn ghost sm" type="button" data-unload="${id}" title="从内存卸载，释放内存；下次用时再自动加载">卸载</button>` : `<button class="btn ghost sm" type="button" data-load="${id}" title="提前载入内存，第一次生成不用等">预加载</button>`}
      <button class="btn ghost sm danger" type="button" data-rm="${id}" data-size="${m.size_gb || ''}" title="删除模型文件">删除</button>${tryBtn}`;
  }
  if (!cloud) return m.engine === 'kokoro' ? '<span class="note">首次合成时自动下载</span>' : `<button class="btn sm" type="button" data-add="${id}">${ic('download', 14)}下载${m.size_gb ? ` ${m.size_gb} GB` : ''}</button>`;
  return `<button class="btn sm" type="button" data-add="${id}" ${p?.connected ? '' : 'disabled title="先连接（填 Key）"'}>${ic('plus', 14)}添加</button>`;
}
async function afterModels() { await Promise.all([refreshModels(), api('/api/providers').then(p => S.providers = p)]); await refreshVoices(); }
const rerender = () => { if (S.route === 'models') pageModels($('#main')); };
function bindRows(el) {
  $$('[data-copyid]', el).forEach(b => b.onclick = () => copy(b.dataset.copyid, `已复制 ${b.dataset.copyid}`));
  $$('[data-trym]', el).forEach(a => a.onclick = () => { if (addToWs({ model: a.dataset.trym }) === 'added') toast(`已加入试音台，现在有 ${S.ws.cands.length} 个声音`); });
  $$('[data-tryt]', el).forEach(a => a.onclick = () => { S.tx.model = a.dataset.tryt; store.set('txModel', S.tx.model); });
  $$('[data-add]', el).forEach(b => b.onclick = async () => {
    b.disabled = true; const m = M(b.dataset.add);
    try { await api('/api/models/add', { model: b.dataset.add }); toast(m.provider === 'local' ? `开始下载 ${mName(m)}` : `已添加 ${mName(m)}`); }
    catch (e) { b.disabled = false; return toast(e.message, 5000); }
    await afterModels(); rerender();
  });
  $$('[data-rm]', el).forEach(b => b.onclick = async () => {
    const m = M(b.dataset.rm), local = m.provider === 'local';
    if (local && !b.classList.contains('armed')) {   // 删除文件：原地二次确认
      b.classList.add('armed'); b.textContent = `确认删除${b.dataset.size ? ` ${b.dataset.size} GB` : ''}`;
      clearTimeout(b._t); b._t = setTimeout(() => { b.classList.remove('armed'); b.textContent = '删除'; }, 4000); return;
    }
    try { await api('/api/models/remove', { model: m.id, delete_files: local }); toast(local ? `已删除 ${mName(m)} 的模型文件` : `已移除 ${mName(m)}`); }
    catch (e) { return toast(e.message, 5000); }
    await afterModels(); refreshStatus(); rerender();
  });
  $$('[data-load]', el).forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = '加载中…'; try { const r = await api('/api/models/load', { model: b.dataset.load }); toast(`已加载，用时 ${r.seconds}s`); } catch (e) { toast(e.message, 5000); } await refreshModels(); refreshStatus(); rerender(); });
  $$('[data-unload]', el).forEach(b => b.onclick = async () => { await api('/api/models/unload', { model: b.dataset.unload }); await refreshModels(); refreshStatus(); rerender(); });
}
async function fetchModels(el, p) {
  S.disc[p.id] = 'loading'; if (el.isConnected) renderProvider(el);
  try { const r = await api('/api/providers/discover', { provider: p.id }); S.disc[p.id] = null; await afterModels(); toast(`从 ${p.kind === 'local' ? 'HuggingFace' : p.name} 查到 ${r.found} 个模型`); }
  catch (e) { S.disc[p.id] = e.message; }
  if (S.route === 'models' && S.sub === p.id) rerender();
}
function bindProvider(el, p) {
  bindRows(el);
  const pe = $('#pEdit', el); if (pe) pe.onclick = () => { S.editProv = p.id; renderProviderForm(el, p); };
  const pdl = $('#pDel', el); if (pdl) pdl.onclick = async () => {
    if (!pdl.classList.contains('armed')) { pdl.classList.add('armed'); pdl.textContent = '确认删除这个 Provider'; setTimeout(() => { pdl.classList.remove('armed'); pdl.textContent = '删除'; }, 4000); return; }
    try { await api('/api/providers/remove', { id: p.id }); } catch (e) { return toast(e.message, 5000); }
    toast(`已删除 ${p.name}，它的已添加模型和保存的 Key 一并删除`, 4000); await afterModels(); location.hash = '#/models/mine';
  };
  $$('form[data-env]', el).forEach(f => f.onsubmit = async e => {
    e.preventDefault(); const inp = $('input', f), v = inp.value.trim(); if (!v) return inp.focus();
    const was = p.connected;
    try { await api('/api/keys', { env: f.dataset.env, value: v }); inp.value = ''; S.keyEdit = null; }
    catch (err) { return toast(err.message, 5000); }
    await afterModels();
    const np = PV(p.id); toast(!was && np.connected ? `已连接 ${p.name}${np.mine ? `，默认加上了 ${np.mine} 个模型` : ''}` : `已保存 ${f.dataset.env}`);
    rerender();
  });
  $$('[data-keyedit]', el).forEach(b => b.onclick = () => { S.keyEdit = b.dataset.keyedit; renderProvider(el); $('form[data-env] input', el)?.focus(); });
  $$('[data-keycancel]', el).forEach(b => b.onclick = () => { S.keyEdit = null; renderProvider(el); });
  $$('[data-delkey]', el).forEach(b => b.onclick = async () => {
    if (!b.classList.contains('armed')) { b.classList.add('armed'); b.textContent = '确认删除'; setTimeout(() => { b.classList.remove('armed'); b.textContent = '删除'; }, 4000); return; }
    await api('/api/keys/delete', { env: b.dataset.delkey }); toast('已从配置文件删除'); await afterModels(); rerender();
  });
  const f = $('#dFetch', el); if (f) f.onclick = () => fetchModels(el, p);
  const mq = $('#mq', el); onText(mq, () => { S.mq[p.id] = mq.value; const pos = mq.selectionStart; renderProvider(el); const n = $('#mq', el); n.focus(); n.setSelectionRange(pos, pos); }, 150);
  const af = $('#dAdd', el); if (af) af.onsubmit = async e => {
    e.preventDefault(); const v = $('input', af).value.trim(); if (!v) return;
    try { const r = await api('/api/models/add', { provider: p.id, remote: v }); toast(`已添加 ${r.model}`); } catch (err) { return toast(err.message, 5000); }
    await afterModels(); rerender();
  };
}
function estimateNum(r) { // 与服务端 hub.estimate 同一口径：只估按字符 / 字节计费的；按 token 计费的返回 {token: true}
  const m = M(r.model), p = m?.price; if (!p || m.provider === 'local') return null;
  if (p.amount == null) return { token: true };
  const t = r.input || '', n = p.unit === 'byte' ? new TextEncoder().encode(t).length : p.unit === 'cjk2' ? [...t].reduce((a, c) => a + (/[\u3400-\u9fff]/.test(c) ? 2 : 1), 0) : [...t].length;
  return { v: p.amount * n / p.per, cur: p.currency };
}
const money = (v, cur) => `${cur === 'CNY' ? '¥' : '$'}${v === 0 ? '0' : v < 0.0001 ? v.toExponential(1) : v.toFixed(4)}`;
function estimateLocal(r) { const e = estimateNum(r); return e && !e.token ? money(e.v, e.cur) : null; }
function priceText(m) {
  const p = m.price; if (!p) return null;
  if (p.text) return esc(p.text);
  if (p.amount === 0) return '免费';
  const sym = p.currency === 'CNY' ? '¥' : '$', per = { 1: '', 1000: '千', 10000: '万', 1000000: '百万' }[p.per] ?? p.per;
  if (['second', 'minute', 'hour'].includes(p.unit)) return `${sym}${+(p.amount / (p.per || 1) * { second: 3600, minute: 60, hour: 1 }[p.unit]).toFixed(3)} / 小时`;   // 识别按音频时长计费
  return `${sym}${p.amount} / ${per}${{ char: '字符', byte: 'UTF-8 字节', cjk2: '字符（汉字按 2）' }[p.unit] || ''}`;
}
function pollPull(main) {
  clearTimeout(S._poll);
  S._poll = setTimeout(async () => {
    const ids = S.models.filter(m => m.status === 'downloading').map(m => m.id); if (!ids.length || S.route !== 'models') return;
    for (const id of ids) {
      const st = await api('/api/models/pull?model=' + encodeURIComponent(id)).catch(() => null); if (!st) continue;
      const pct = st.total ? Math.min(100, st.done / st.total * 100) : 0;
      const bar = $(`[data-bar="${CSS.escape(id)}"]`), lab = $(`[data-prog="${CSS.escape(id)}"]`);
      if (bar) bar.style.transform = `scaleX(${pct / 100})`; if (lab) lab.textContent = `${(st.done / 1e9).toFixed(2)} / ${(st.total / 1e9).toFixed(2)} GB`;
      if (st.state === 'done' || st.state === 'error') { toast(st.state === 'error' ? `下载失败：${st.error}` : '下载完成，已校验', st.state === 'error' ? 6000 : 2400); await afterModels(); return pageModels(main); }
    }
    pollPull(main);
  }, 1500);
}

/* ============ API ============ */
/* ============ 转写（语音识别） ============ */
// 一个文件进、一段文字出。选项只显示当前模型支持的；有分句时间戳时点一句就跳到那里播放。
const TX_LANGS = [['', '自动识别'], ['zh', '中文'], ['en', '英语'], ['yue', '粤语'], ['ja', '日语'], ['ko', '韩语']];
S.tx = { model: store.get('txModel', null), language: store.get('txLang', ''), hotwords: '', prompt: '', words: false, diarize: false,
  file: null, url: null, dur: null, busy: null, err: null, rec: null, list: null };
const clock = s => { s = Math.max(0, s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = Math.floor(s % 60); return `${h ? h + ':' + String(m).padStart(2, '0') : m}:${String(x).padStart(2, '0')}`; };
const mineSTT = () => mine().filter(m => !isTTS(m));
function txModel() {
  const ms = mineSTT(), m = M(S.tx.model);
  return m && !isTTS(m) && m.mine ? m : ms.find(usable) || ms[0] || null;
}

function pageTranscribe(main) {
  const ready = mineSTT().some(usable);   // 一个能用的都没有（包括还在下载）：显示下载入口或下载进度
  main.innerHTML = `
    <div class="head"><div><h1>转写</h1><p>把录音、视频转成文字或字幕。本地模型在这台 Mac 上识别，文件不离开本机；选云端模型时，文件会发给那家 Provider。</p></div><button class="cli" type="button" data-copy="vox transcribe 录音.m4a">vox transcribe</button></div>
    ${ready ? '' : txEmpty()}
    <section class="sec tx-in" ${ready ? '' : 'hidden'}>
      <label class="drop ${S.tx.file ? 'has' : ''}" id="txDrop">
        <input type="file" id="txFile" accept="audio/*,video/*" hidden>
        <span class="drop-ic">${ic(S.tx.file ? 'wave' : 'upload', 22)}</span>
        ${S.tx.file ? `<span class="drop-t"><b>${esc(S.tx.file.name)}</b><span>${(S.tx.file.size / 1e6).toFixed(1)} MB${S.tx.dur ? ` · ${clock(S.tx.dur)}` : ''} · 点这里换一个</span></span>`
          : '<span class="drop-t"><b>拖入音频或视频，或点这里选择</b><span>mp3、m4a、wav、mp4、mov……ffmpeg 能读的都行</span></span>'}
      </label>
      <div class="tx-opts" id="txOpts"></div>
      <div class="tx-go"><span class="note" id="txEst"></span><span class="sp"></span><button class="btn primary" type="button" id="txGo">${ic('wave', 15)}开始转写</button></div>
    </section>
    <section class="sec tx-out" id="txOut" hidden></section>
    <section class="sec" id="txList"></section>`;
  const inp = $('#txFile', main), drop = $('#txDrop', main);
  inp.onchange = () => inp.files[0] && pickFile(inp.files[0], main);
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) pickFile(f, main); };
  $('#txGo', main).onclick = () => runTranscribe(main);
  $$('.head [data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy, '已复制命令'));
  bindTxEmpty(main);
  renderTxOpts(main); renderTxOut(main); loadTxList(main);
}
function txEmpty() {
  const dl = S.models.find(x => !isTTS(x) && x.status === 'downloading');
  if (dl) return `<div class="empty tx-dl"><b>正在下载 ${esc(mName(dl))}</b><span data-txprog>准备中…</span>
    <div class="bar"><i data-txbar></i></div><span class="note">下载完就能用，这个页面会自动刷新；也可以先去做别的。</span></div>`;
  const local = S.models.find(x => !isTTS(x) && x.provider === 'local'), cloud = S.models.filter(x => !isTTS(x) && x.provider !== 'local');
  return `<div class="empty"><b>还没有能用的识别模型</b>下载一个本地模型，完全离线识别；或者连接支持识别的云端 Provider（${[...new Set(cloud.map(x => esc(PV(x.provider)?.name || x.provider)))].join('、')}）。
    <div class="empty-a">${local ? `<button class="btn primary" type="button" data-txadd="${esc(local.id)}">${ic('download', 14)}下载 ${esc(mName(local))} · ${local.size_gb} GB</button>` : ''}
    <a class="btn" href="#/models/mine">去模型页</a></div></div>`;
}
function bindTxEmpty(main) {
  $$('[data-txadd]', main).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = '开始下载…';
    try { await api('/api/models/add', { model: b.dataset.txadd }); await refreshModels(); pageTranscribe(main); }   // 先刷新状态，页面才知道它在下载
    catch (e) { toast(e.message, 5000); b.disabled = false; }
  });
  if (S.models.some(x => !isTTS(x) && x.status === 'downloading')) pollTxPull(main);
}
// 转写页里直接显示下载进度（和模型页用同一个接口），下载完自动变成可用
function pollTxPull(main) {
  clearTimeout(S._txPoll);
  S._txPoll = setTimeout(async () => {
    const dl = S.models.find(x => !isTTS(x) && x.status === 'downloading'); if (!dl || S.route !== 'transcribe') return;
    const st = await api('/api/models/pull?model=' + encodeURIComponent(dl.id)).catch(() => null);
    if (st) {
      const bar = $('[data-txbar]', main), lab = $('[data-txprog]', main), pct = st.total ? Math.min(1, st.done / st.total) : 0;
      if (bar) bar.style.transform = `scaleX(${pct})`;
      if (lab) lab.textContent = st.total ? `${(st.done / 1e9).toFixed(2)} / ${(st.total / 1e9).toFixed(2)} GB · ${Math.round(pct * 100)}%` : '准备中…';
      if (st.state === 'done' || st.state === 'error') {
        toast(st.state === 'error' ? `下载失败：${st.error}` : '下载完成，已校验，可以转写了', st.state === 'error' ? 6000 : 3000);
        await refreshModels(); refreshStatus(); return pageTranscribe(main);
      }
    }
    pollTxPull(main);
  }, 1500);
}
function renderTxOpts(main) {
  const el = $('#txOpts', main); if (!el) return;
  const m = txModel(); if (!m) return;
  const ms = mineSTT(), c = m.caps;
  el.innerHTML = `
    <div class="field"><div class="lbl"><span>模型</span></div>
      ${dd('txModel', { value: m.id, label: '识别模型', groups: modelGroups(ms).map(g => ({ ...g, items: g.items.map(it => ({ ...it, tags: [...CAP_T(M(it.value)).filter(([k]) => M(it.value).caps[k] && ['diarize', 'segments'].includes(k)).map(([, t]) => [t, 'mute']), ...it.tags] })) })), onChange: v => { S.tx.model = v; store.set('txModel', v); renderTxOpts(main); } })}</div>
    <div class="field"><div class="lbl"><span>语种</span></div>
      ${dd('txLang', { value: S.tx.language, label: '语种', groups: [{ items: TX_LANGS.map(([k, t]) => ({ value: k, label: t })) }], onChange: v => { S.tx.language = v; store.set('txLang', v); renderTxOpts(main); } })}</div>
    ${c.hotwords ? `<div class="field wide"><div class="lbl"><span>热词</span></div><input class="in" id="txHot" value="${esc(S.tx.hotwords)}" placeholder="人名、产品名，逗号分隔：vox，Qwen3，Obsidian"></div>` : ''}
    ${c.prompt ? `<div class="field wide"><div class="lbl"><span>上下文提示</span></div><input class="in" id="txPrompt" value="${esc(S.tx.prompt)}" placeholder="这段录音讲什么、有哪些专有名词（可不填）"></div>` : ''}
    ${c.words || c.diarize ? `<div class="field wide tx-flags">${c.diarize ? `<label class="pf-check"><input type="checkbox" id="txDia" ${S.tx.diarize ? 'checked' : ''}> 区分说话人</label>` : ''}${c.words ? `<label class="pf-check"><input type="checkbox" id="txWords" ${S.tx.words ? 'checked' : ''}> 逐词时间戳</label>` : ''}</div>` : ''}
    <p class="note wide">${esc(m.about || '')}${c.segments || c.diarize ? '' : ' 这个模型只给整段文字，要字幕请选带分句时间戳的模型。'}</p>`;
  onText($('#txHot', el), () => S.tx.hotwords = $('#txHot', el).value);
  onText($('#txPrompt', el), () => S.tx.prompt = $('#txPrompt', el).value);
  const dia = $('#txDia', el), w = $('#txWords', el);
  if (dia) dia.onchange = () => S.tx.diarize = dia.checked;
  if (w) w.onchange = () => S.tx.words = w.checked;
  updateTxGo(main);
}
function updateTxGo(main) {
  const m = txModel(), go = $('#txGo', main), est = $('#txEst', main); if (!go) return;
  go.disabled = !S.tx.file || !!S.tx.busy || !m || !usable(m);
  const p = m?.price, perSec = p && p.amount != null ? p.amount / (p.per || 1) / ({ second: 1, minute: 60, hour: 3600 }[p.unit] || NaN) : NaN;
  est.textContent = !m ? '' : !usable(m) ? (m.provider === 'local' ? '这个模型还没下载' : `${PV(m.provider)?.name || ''} 还没连接`)
    : !S.tx.file ? '先选一个文件' : m.provider === 'local' ? `本机识别，免费${m.status === 'loaded' ? '' : ' · 第一次要先加载模型'}`
    : isFinite(perSec) && S.tx.dur ? (perSec ? `云端识别，约 ${money(perSec * S.tx.dur, p.currency)}` : '云端识别，免费') : '云端识别，按音频时长计费';
}
function pickFile(f, main) {
  if (S.tx.url) URL.revokeObjectURL(S.tx.url);
  Object.assign(S.tx, { file: f, url: URL.createObjectURL(f), dur: null, err: null });
  const a = new Audio(); a.preload = 'metadata'; a.src = S.tx.url;   // 用浏览器读时长，给费用预估用
  a.onloadedmetadata = () => { S.tx.dur = isFinite(a.duration) ? a.duration : null; if (S.route === 'transcribe') pageTranscribe(main); };
  pageTranscribe(main);
}
function runTranscribe(main) {
  const m = txModel(); if (!m || !S.tx.file || S.tx.busy) return;
  const fd = new FormData();
  fd.append('file', S.tx.file, S.tx.file.name);
  const opts = { model: m.id, language: S.tx.language, hotwords: m.caps.hotwords ? S.tx.hotwords : '', prompt: m.caps.prompt ? S.tx.prompt : '',
    words: m.caps.words && S.tx.words ? 'true' : '', diarize: m.caps.diarize && S.tx.diarize ? 'true' : '', source: 'webui' };
  Object.entries(opts).forEach(([k, v]) => v && fd.append(k, v));
  // XHR 而不是 fetch：要上传进度（几百 MB 的视频上传也要一会儿）
  const x = new XMLHttpRequest(), t0 = Date.now();
  S.tx.busy = { phase: '上传中', pct: 0, t0 }; S.tx.err = null; renderTxOut(main); updateTxGo(main);
  const tick = setInterval(() => { if (S.route === 'transcribe') renderTxOut(main); else clearInterval(tick); }, 500);
  x.upload.onprogress = e => { if (e.lengthComputable) S.tx.busy.pct = e.loaded / e.total; };
  x.upload.onload = () => { S.tx.busy.phase = m.provider === 'local' ? (m.status === 'loaded' ? '识别中' : '加载模型并识别中') : `${PV(m.provider)?.name || ''} 识别中`; };
  x.onloadend = async () => {
    clearInterval(tick);
    let j = null; try { j = JSON.parse(x.responseText); } catch {}
    S.tx.busy = null;
    if (x.status === 200 && j && !j.error) { S.tx.rec = j; S.tx.list = null; if (m.provider === 'local' && m.status !== 'loaded') refreshModels().then(refreshStatus); }
    else S.tx.err = j?.error?.message || j?.error || `HTTP ${x.status || '连接中断'}`;
    if (S.route === 'transcribe') { renderTxOut(main); updateTxGo(main); loadTxList(main); }
  };
  x.open('POST', '/api/transcribe'); x.send(fd);
}
function renderTxOut(main) {
  const el = $('#txOut', main); if (!el) return;
  const b = S.tx.busy, r = S.tx.rec;
  el.hidden = !b && !r && !S.tx.err;
  if (b) {
    const s = (Date.now() - b.t0) / 1000;
    el.innerHTML = `<div class="tx-busy"><span class="spin"></span><b>${b.phase === '上传中' ? `上传中 ${Math.round(b.pct * 100)}%` : b.phase}…</b><span class="note">${clock(s)}${S.tx.dur && b.phase !== '上传中' ? ` · 音频 ${clock(S.tx.dur)}` : ''}</span></div>`;
    return;
  }
  if (S.tx.err) { el.innerHTML = `<div class="tx-busy"><span class="err">识别失败：${esc(S.tx.err)}</span></div>`; return; }
  if (!r) return;
  const rm = M(r.request.model), live = S.tx.file && S.tx.file.name === r.file, spk = new Set(r.segments.map(x => x.speaker).filter(Boolean));
  const facts = [r.duration ? `音频 ${clock(r.duration)}` : '', `用时 ${r.elapsed}s`, r.language ? `语种 ${esc(r.language)}` : '', spk.size ? `${spk.size} 位说话人` : '',
    r.cost?.amount != null ? money(r.cost.amount, r.cost.currency) : '', r.cached ? '缓存' : ''].filter(Boolean);
  const exp = f => `<a class="btn ghost sm" href="/api/transcripts/${r.id}?format=${f}&download=1" title="下载 ${f.toUpperCase()}">${f.toUpperCase()}</a>`;
  const fmts = r.timed ? ['txt', 'srt', 'vtt', 'json'] : ['txt', 'json'];   // 没有分句时间戳就不给字幕格式，并说明原因
  el.innerHTML = `
    <div class="sec-h"><h3>${ic('wave', 15)}${esc(r.file)}</h3><span class="note">${esc(rm ? mName(rm) : r.request.model)} · ${facts.join(' · ')}</span><span class="sp"></span>
      ${r.timed ? '' : '<span class="note" title="这个模型只给整段文字，没有分句时间戳">无时间戳，导不出字幕</span>'}<button class="btn sm" type="button" id="txCopy">${ic('copy', 14)}复制文字</button>${fmts.map(exp).join('')}</div>
    ${live ? `<audio class="tx-audio" controls src="${S.tx.url}" id="txAudio"></audio>` : ''}
    ${r.timed && r.segments.length ? `<div class="tx-segs">${r.segments.map(x => `<button class="tx-seg" type="button" data-at="${x.start}" ${live ? '' : 'disabled'}><time>${clock(x.start)}</time>${x.speaker ? `<b class="spk" style="--h:${[...spk].indexOf(x.speaker) * 67}">${esc(x.speaker)}</b>` : ''}<span>${esc(x.text)}</span></button>`).join('')}</div>`
      : `<div class="tx-text">${esc(r.text) || '<span class="note">（没有识别出文字）</span>'}</div>`}`;
  $('#txCopy', el).onclick = () => copy(r.timed && spk.size ? r.segments.map(x => `[${x.speaker}] ${x.text}`).join('\n') : r.text, '已复制');
  const au = $('#txAudio', el);
  $$('[data-at]', el).forEach(bt => bt.onclick = () => { if (au) { au.currentTime = +bt.dataset.at; au.play(); } });
}
async function loadTxList(main) {
  const el = $('#txList', main); if (!el) return;
  if (!S.tx.list) { try { S.tx.list = await api('/api/transcripts?limit=30'); } catch { S.tx.list = []; } }
  if (S.route !== 'transcribe') return;
  const rs = S.tx.list;
  el.hidden = !rs.length;
  el.innerHTML = `<div class="sec-h"><h3>最近的转写</h3><span class="n">${rs.length}</span><span class="sp"></span><span class="note">和 vox transcripts 共享</span></div>
    <div class="tx-rows">${rs.map(r => `<div class="tx-row ${S.tx.rec?.id === r.id ? 'on' : ''}"><button class="tx-open" type="button" data-open="${r.id}"><b>${esc(r.file)}</b><span>${esc(r.preview || '（空）')}</span></button>
      <span class="note">${esc(M(r.request.model) ? mName(M(r.request.model)) : r.request.model)} · ${r.duration ? clock(r.duration) : ''} · ${ago(r.ts)}</span>
      <button class="btn ghost sm danger" type="button" data-del="${r.id}" aria-label="删除这条转写" title="删除这条转写">${ic('x', 14)}</button></div>`).join('')}</div>`;
  $$('[data-open]', el).forEach(b => b.onclick = async () => { S.tx.rec = await api(`/api/transcripts/${b.dataset.open}`); S.tx.err = null; renderTxOut(main); loadTxList(main); $('#txOut', main).scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
  $$('[data-del]', el).forEach(b => b.onclick = async () => {
    if (!b.classList.contains('armed')) { b.classList.add('armed'); b.innerHTML = '确认删除'; clearTimeout(b._t); b._t = setTimeout(() => { b.classList.remove('armed'); b.innerHTML = ic('x', 14); }, 4000); return; }
    await api('/api/transcripts/delete', { id: b.dataset.del }); if (S.tx.rec?.id === b.dataset.del) S.tx.rec = null; S.tx.list = null; renderTxOut(main); loadTxList(main); toast('已删除'); });
}

function pageApi(main) {
  const ready = mineTTS().filter(usable), m = M(S.apiModel) && usable(M(S.apiModel)) && isTTS(M(S.apiModel)) ? M(S.apiModel) : ready[0] || S.models.find(isTTS);
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'builtin');
  const r = { model: m.id, input: '你好，这是来自 vox 的声音。', ...(m.caps.voices ? { voice: vs[0]?.voice || m.default_voice } : {}), ...(m.caps.design ? { instructions: S.cat.design[1] } : {}) };
  const js = `const res = await fetch("${ORIGIN}/v1/audio/speech", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${JSON.stringify({ ...r, response_format: 'mp3' })}),\n});\nconst audio = new Audio(URL.createObjectURL(await res.blob()));\naudio.play();`;
  const code = { curl: cmdOf(r, 'curl'), python: cmdOf(r, 'python'), js, cli: cmdOf(r, 'cli') };
  const tabs = { curl: 'cURL', python: 'Python', js: 'JavaScript', cli: 'CLI' };
  const eps = [
    ['合成', [['POST', '/v1/audio/speech', 'OpenAI 兼容，返回音频。扩展参数 seed、lang、temperature 等；响应头带 X-Vox-Seed'], ['POST', '/api/speech', '合成并返回 JSON：实际种子、时长、音频地址'], ['GET', '/api/history', '合成历史，与 CLI 共享']]],
    ['模型', [['GET', '/v1/models', 'OpenAI 兼容：已添加的模型'], ['GET', '/api/models', '全部模型与状态；?mine=1 只看已添加的，?provider= 只看一家'], ['POST', '/api/models/add · remove', '添加 / 移除模型（本地模型即下载 / 删除文件）'],
      ['POST', '/api/providers/discover', '在线查询一家现在提供的模型'], ['POST', '/api/models/load · unload', '预加载 / 卸载本地模型']]],
    ['音色', [['GET', '/api/voices', '音色库，可按 model、lang、gender、q 筛选'], ['POST', '/api/voices/sample', '生成或取音色样本'], ['POST', '/api/asr', '读音校对'],
      ['GET', '/api/presets', '预设列表；POST 保存，/api/presets/delete 删除'], ['POST', '/api/clones', '新建克隆音色（multipart：file + name / text / consent）'],
      ['GET', '/api/clones', '克隆音色；/api/clones/update、/api/clones/consent、/api/clones/delete']]],
    ['识别', [['POST', '/v1/audio/transcriptions', 'OpenAI 兼容：multipart 上传音频，返回 json / text / srt / vtt / verbose_json'], ['POST', '/api/transcribe', '识别并返回完整记录（分句、说话人、费用）'],
      ['GET', '/api/transcripts', '转写记录；/api/transcripts/<id>?format=srt 导出']]],
    ['给 Agent', [['GET', '/llms.txt', '接口说明与已添加的模型清单']]]];
  main.innerHTML = `
    <div class="head"><div><h1>API</h1><p>兼容 OpenAI：把客户端的 Base URL 换成下面这个，就能调用全部已添加的模型。</p></div></div>
    <div class="card base-card"><div class="lbl"><span>Base URL</span><span class="key">api_key 随便填，本地服务不校验</span></div>
      <div class="base"><code class="mono">${ORIGIN}/v1</code><button class="btn sm" type="button" data-copy="${ORIGIN}/v1">${ic('copy', 14)}复制</button><a class="lnk" href="/llms.txt" target="_blank">给 Agent 的说明 llms.txt${ic('ext', 13)}</a></div></div>
    <div class="card code-card"><div class="equiv-head"><div class="seg">${Object.entries(tabs).map(([k, t]) => `<button type="button" data-at="${k}" class="${S.apiTab === k ? 'on' : ''}">${t}</button>`).join('')}</div><span class="sp"></span>
      ${dd('apiModel', { value: m.id, cls: 'sel', label: '示例用的模型', width: 300, btnTags: false, groups: modelGroups(ready, { status: false }).map(g => ({ ...g, items: g.items.map(it => ({ ...it, sub: it.value })) })), onChange: v => { S.apiModel = v; pageApi(main); } })}
      <button class="btn ghost sm" type="button" id="apiCopy">${ic('copy', 14)}复制</button></div><pre>${esc(code[S.apiTab])}</pre></div>
    <div class="card"><table class="ep">${eps.map(([g, rows]) => `<tbody><tr class="ep-g"><th colspan="3">${g}</th></tr>${rows.map(e => `<tr><td class="ep-m">${e[0]}</td><td class="ep-p">${esc(e[1])}</td><td>${esc(e[2])}</td></tr>`).join('')}</tbody>`).join('')}</table></div>
    <div class="card"><div class="lbl"><span>统一的参数名</span></div>
      <table class="ep names"><thead><tr><th></th><th>模型</th><th>音色</th><th>情绪 / 声音描述</th><th>语速</th><th>种子</th></tr></thead>
        <tbody><tr><td class="ep-m">HTTP</td><td><code>model</code></td><td><code>voice</code></td><td><code>instructions</code></td><td><code>speed</code></td><td><code>seed</code></td></tr>
        <tr><td class="ep-m">CLI</td><td><code>-m</code></td><td><code>-v</code></td><td><code>-i</code></td><td><code>-s</code></td><td><code>--seed</code></td></tr></tbody></table>
      <p class="note">音色也可以写引用：<code>qwen3:serena</code>、<code>preset:&lt;id&gt;</code>（引用里已经带上了模型），或克隆音色 <code>clone:&lt;id&gt;</code>（配合支持克隆的模型）。</p></div>`;
  $$('[data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy));
  $$('[data-at]', main).forEach(b => b.onclick = () => { S.apiTab = b.dataset.at; pageApi(main); });
  $('#apiCopy', main).onclick = () => copy(code[S.apiTab], '已复制示例代码');
}

/* ---------- 启动 ---------- */
(async () => {
  try {
    await Promise.all([refreshModels(), refreshVoices(), refreshStatus(),
      api('/api/catalog').then(c => S.cat = c), api('/api/providers').then(p => S.providers = p), api('/api/settings').then(s => S.settings = s), api('/api/history?limit=80').then(h => S.hist = h)]);
  } catch (e) { $('#main').innerHTML = `<div class="empty"><b>连不上 vox 服务</b>${esc(e.message)}。在终端运行 <code>vox serve</code> 后刷新。</div>`; return; }
  route();
  setInterval(refreshStatus, 5000);
})();
})();
