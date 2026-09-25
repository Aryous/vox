/* vox WebUI：音色库 / 试音台 / 模型 / API。只调用 vox 的原生 API（/api/*），与 CLI 共用同一套模型、音色、参数。 */
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
  models: [], voices: [], providers: [], status: null, cat: { instructions: [], design: [] }, settings: { sample_text: '', favorites: [] }, hist: [], myv: [],
  vf: store.get('vf', { q: '', model: 'all', gender: '', lang: '', fav: false }), vlimit: 60,
  slots: store.get('slots', null), compare: store.get('compare', false), text: store.get('text', QUICK[0]),
  runs: [], feedStar: false, equiv: store.get('equiv', 'cli'), apiTab: 'curl', autoAsr: store.get('autoAsr', true),
};

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(typeof j.error === 'string' ? j.error : j.error?.message || `HTTP ${r.status}`);
  return j;
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
  dup: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5M14 11.5v5M11.5 14h5"/>',
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
const voiceName = (model, voice) => S.voices.find(v => v.model === model && v.voice === voice)?.name || voice;

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
  if (e.target.closest('input,textarea,select')) return;
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
async function refreshVoices() { S.voices = await api('/api/voices'); }

/* ---------- 路由 ---------- */
const PAGES = { voices: pageVoices, playground: pagePlayground, models: pageModels, api: pageApi };
function route() {
  let [, r, sub] = location.hash.match(/^#\/(\w+)(?:\/([\w-]+))?/) || [];
  if (r === 'providers') { r = 'models'; history.replaceState(null, '', `#/models${sub ? '/' + sub : ''}`); } // 旧链接
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
function filteredVoices(ignoreLang) {
  const f = ignoreLang === true ? { ...S.vf, lang: '' } : S.vf, q = f.q.trim().toLowerCase();
  const okModel = v => { const m = M(v.model); return f.model === 'all' || f.model === 'ready' || (f.model === 'my' ? v.kind === 'custom' : f.model.startsWith('p:') ? m?.provider === f.model.slice(2) && v.kind === 'preset' : v.model === f.model && v.kind === 'preset'); };
  return S.voices.filter(v => okModel(v)
    && (!f.gender || v.gender === f.gender) && (!f.lang || v.lang === f.lang) && (!f.fav || S.settings.favorites.includes(v.ref))
    && (!q || `${v.ref} ${v.name} ${v.description} ${v.lang}`.toLowerCase().includes(q)));
}
function pageVoices(main) {
  const vs = filteredVoices(), f = S.vf, ms = mine().filter(m => m.caps.voices);
  const local = ms.filter(m => m.provider === 'local'), provs = [...new Set(ms.filter(m => m.provider !== 'local').map(m => m.provider))];
  const langs = [...new Set(filteredVoices(true).map(v => v.lang).filter(Boolean))].slice(0, 14);
  const nMy = S.voices.filter(v => v.kind === 'custom').length, nPreset = S.voices.length - nMy;
  const cloudOff = S.providers.filter(p => p.kind === 'cloud' && !p.connected).length;
  main.innerHTML = `
    <div class="head"><div><h1>音色库</h1><p>${nPreset} 个音色，来自我的 ${ms.length} 个模型，都读同一段样本。${cloudOff ? `<a href="#/models/openrouter">连接云端 Provider</a> 能听到更多。` : ''}</p></div>
      <button class="cli" type="button" data-copy="vox voices --json">vox voices --json</button></div>
    <div class="sampleline" id="sampleLine"><span class="lbl-i">样本文本</span><q>${esc(S.settings.sample_text)}</q><button class="btn ghost sm" type="button" id="editSample">修改</button></div>
    <div class="filters">
      <label class="search">${ic('search', 15)}<input class="in" id="vq" placeholder="搜索名字、描述、音色 ID" value="${esc(f.q)}" aria-label="搜索音色"></label>
      <div class="seg" role="group" aria-label="音色类型">
        <button type="button" data-fm="all" class="${f.model !== 'my' ? 'on' : ''}">全部</button>
        <button type="button" data-fm="my" class="${f.model === 'my' ? 'on' : ''}">自定义${nMy ? ` <span class="n">${nMy}</span>` : ''}</button>
      </div>
      <select class="in sel" id="fprov" aria-label="按模型筛选"><option value="">所有模型</option>
        ${local.length ? `<optgroup label="本地">${local.map(m => `<option value="${m.id}" ${f.model === m.id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</optgroup>` : ''}
        ${provs.map(pid => `<optgroup label="${esc(PV(pid)?.name || pid)}"><option value="p:${pid}" ${f.model === 'p:' + pid ? 'selected' : ''}>${esc(PV(pid)?.name || pid)} 全部</option>${ms.filter(m => m.provider === pid).map(m => `<option value="${m.id}" ${f.model === m.id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</optgroup>`).join('')}</select>
      <div class="seg" role="group" aria-label="按性别筛选">${[['', '不限'], ['女', '女声'], ['男', '男声']].map(([k, t]) => `<button type="button" data-fg="${k}" class="${f.gender === k ? 'on' : ''}">${t}</button>`).join('')}</div>
      <button type="button" class="chip fav ${f.fav ? 'on' : ''}" id="ffav" aria-pressed="${f.fav}">${ic('star', 13)}收藏 <span class="n">${S.settings.favorites.length}</span></button>
    </div>
    ${langs.length > 1 ? `<div class="chips langs"><button class="chip ${!f.lang ? 'on' : ''}" data-fl="">所有语言</button>${langs.map(l => `<button class="chip ${f.lang === l ? 'on' : ''}" data-fl="${esc(l)}">${esc(l)}</button>`).join('')}</div>` : ''}
    <div class="grid" id="vgrid"></div>
    <div class="more" id="more"></div>`;
  const grid = $('#vgrid', main);
  if (!vs.length) grid.outerHTML = f.model === 'my' ? '<div class="empty"><b>还没有自定义音色</b>在试音台调好声音后，点「存为我的音色」，就会出现在这里。</div>'
    : S.voices.length ? '<div class="empty"><b>没有符合条件的音色</b>换个筛选条件试试。</div>'
    : '<div class="empty"><b>还没有能用的模型</b>去<a href="#/models/local">下载一个本地模型</a>，或<a href="#/models/openrouter">连接云端 Provider</a>。</div>';
  else grid.innerHTML = vs.slice(0, S.vlimit).map(voiceCard).join('');
  if (vs.length > S.vlimit) $('#more', main).innerHTML = `<button class="btn" type="button" id="moreBtn">再显示 ${Math.min(60, vs.length - S.vlimit)} 个（共 ${vs.length}）</button>`;
  bindVoices(main, vs);
}
function voiceCard(v) {
  const m = M(v.model), ok = usable(m), fav = S.settings.favorites.includes(v.ref);
  const tags = [v.gender ? `${v.gender}声` : '', v.lang, v.kind === 'custom' ? '自定义' : ''].filter(Boolean);
  return `<article class="vc" style="--m:${hue(v.model)}" data-ref="${esc(v.ref)}" data-url="${esc(v.sample.url)}">
    <div class="vc-top">
      <button class="pb" type="button" data-sample="${esc(v.ref)}" data-url="${esc(v.sample.url)}" ${ok ? '' : 'disabled'} aria-label="试听 ${esc(v.name)}">${ic('play', 14)}</button>
      <div class="vc-name"><b>${esc(v.name)}</b><code title="${esc(m?.name || v.model)}">${esc(v.ref)}</code></div>
      <button class="star ${fav ? 'on' : ''}" type="button" data-fav="${esc(v.ref)}" aria-pressed="${fav}" aria-label="收藏 ${esc(v.name)}">${ic('star', 16)}</button>
    </div>
    <p>${esc(v.description) || '<span class="mute">没有描述</span>'}</p>
    <canvas class="mini" data-url="${esc(v.sample.url)}" ${v.sample.cached ? '' : 'hidden'}></canvas>
    <div class="vc-foot">
      <span class="tags">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</span>
      ${ok ? `<a class="btn sm" href="#/playground" data-try="${esc(v.ref)}">试音${ic('arrow', 13)}</a>` : `<a class="btn sm" href="#/models/${m?.provider || 'local'}">${m ? '模型不可用' : '模型已移除'}</a>`}
    </div></article>`;
}
function bindVoices(main, vs) {
  const vq = $('#vq', main); onText(vq, () => { S.vf.q = vq.value; store.set('vf', S.vf); S.vlimit = 60; pageVoices(main); const i = $('#vq', main); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 180);
  $$('[data-fm]', main).forEach(b => b.onclick = () => { S.vf.model = b.dataset.fm; S.vf.lang = ''; S.vlimit = 60; store.set('vf', S.vf); pageVoices(main); });
  $('#fprov', main).onchange = e => { S.vf.model = e.target.value || 'all'; S.vf.lang = ''; S.vlimit = 60; store.set('vf', S.vf); pageVoices(main); };
  $$('[data-fg]', main).forEach(b => b.onclick = () => { S.vf.gender = b.dataset.fg; store.set('vf', S.vf); pageVoices(main); });
  $$('[data-fl]', main).forEach(b => b.onclick = () => { S.vf.lang = b.dataset.fl; store.set('vf', S.vf); pageVoices(main); });
  $('#ffav', main).onclick = () => { S.vf.fav = !S.vf.fav; store.set('vf', S.vf); pageVoices(main); };
  const more = $('#moreBtn', main); if (more) more.onclick = () => { S.vlimit += 60; pageVoices(main); };
  $$('[data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy, '已复制命令'));
  $$('[data-sample]', main).forEach(b => b.onclick = () => playSample(b.dataset.sample, b));
  $$('[data-fav]', main).forEach(b => b.onclick = () => toggleFav(b.dataset.fav, b));
  $$('[data-try]', main).forEach(a => a.onclick = () => tryVoice(a.dataset.try));
  $$('canvas.mini:not([hidden])', main).forEach(cv => drawWave(cv, cv.dataset.url));
  $('#editSample', main).onclick = () => {
    const line = $('#sampleLine', main);
    line.innerHTML = `<span class="lbl-i">样本文本</span><input class="in" id="sampleIn" value="${esc(S.settings.sample_text)}"><button class="btn primary sm" type="button" id="saveSample">保存</button><button class="btn ghost sm" type="button" id="cancelSample">取消</button><span style="width:100%;font-size:12px;color:var(--mute)">{name} 会替换成音色名字。改动后，样本在下次试听时按新文本重新生成。</span>`;
    $('#sampleIn', line).focus();
    $('#cancelSample', line).onclick = () => pageVoices(main);
    $('#saveSample', line).onclick = async () => { S.settings = await api('/api/settings', { sample_text: $('#sampleIn', line).value.trim() }); await refreshVoices(); pageVoices(main); toast('样本文本已更新'); };
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
const ensureSlots = () => { if (!S.slots || !S.slots.length) S.slots = [newSlot()]; };
function tryVoice(ref) {
  const v = S.voices.find(x => x.ref === ref); if (!v) return;
  ensureSlots(); const s = slot(); Object.assign(s, newSlot(v.request || { model: v.model, voice: v.voice }));
  saveSlots();
}

/* ============ 试音台 ============ */
function newSlot(p = {}) {
  const model = M(p.model)?.id || (mine().find(m => usable(m) && m.caps.voices) || mine()[0] || S.models[0])?.id;
  const m = M(model);
  return { model, voice: p.voice || m?.default_voice || '', instructions: p.instructions || '', speed: p.speed ?? 1, seedMode: p.seed != null ? 'fixed' : 'random',
    seed: p.seed ?? Math.floor(Math.random() * 1e6), lang: p.lang || 'chinese', ...GEN_DEFAULT, ...Object.fromEntries(Object.keys(GEN_DEFAULT).filter(k => p[k] != null).map(k => [k, p[k]])) };
}
const slot = () => S.slots[0];   // 单路只有一组参数；对比模式的候选单独存（S.cands）
const saveSlots = () => { store.set('slots', S.slots); store.set('compare', S.compare); };
const LETTER = i => String.fromCharCode(65 + i);

function reqOf(s, text) {
  const m = M(s.model), has = k => m.params.includes(k), r = { model: m.id, input: text ?? S.text };
  if (has('voice') && s.voice) r.voice = s.voice;
  if (has('instructions') && s.instructions.trim()) r.instructions = s.instructions.trim();
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

function pagePlayground(main) {
  ensureSlots();
  S.slots = [M(slot().model) ? slot() : newSlot()];
  if (S.compare) return pageCompare(main);
  main.innerHTML = `
    <div class="head"><div><h1>试音台</h1><p>写一句话，调好声音，生成。结果会记下完整参数，随时复现。</p></div>${modeSeg()}</div>
    <div class="pg">
      <aside class="panel" id="panel" aria-label="参数"></aside>
      <section>
        <div class="compose">
          <textarea class="in" id="text" aria-label="要合成的文本" placeholder="输入要合成的文字…">${esc(S.text)}</textarea>
          <div class="chips">${QUICK.map((q, i) => `<button type="button" class="chip" data-quick="${i}">${esc(q.length > 16 ? q.slice(0, 16) + '…' : q)}</button>`).join('')}</div>
          <div class="compose-bar"><span class="count" id="count"></span><span class="sp"></span><span class="count" id="hint"></span>
            <button class="btn primary lg" type="button" id="gen">生成 <kbd>⌘↵</kbd></button></div>
        </div>
        <div class="equiv" id="equiv"></div>
        <div class="feed-head"><h2>结果</h2><span class="sp"></span>
          <label class="chip ${S.autoAsr ? 'on' : ''}" style="cursor:pointer"><input type="checkbox" id="autoAsr" ${S.autoAsr ? 'checked' : ''} hidden> 自动读音校对</label>
          <button type="button" class="chip fav ${S.feedStar ? 'on' : ''}" id="feedStar" aria-pressed="${S.feedStar}">${ic('star', 13)}只看收藏</button></div>
        <div class="feed" id="feed"></div>
      </section>
    </div>`;
  const ta = $('#text', main);
  ta.oninput = () => { S.text = ta.value; store.set('text', S.text); updateCompose(main); };
  $$('[data-quick]', main).forEach(b => b.onclick = () => { ta.value = S.text = QUICK[+b.dataset.quick]; store.set('text', S.text); updateCompose(main); });
  bindModeSeg(main);
  $('#gen', main).onclick = () => generate(main);
  ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); generate(main); } };
  $('#autoAsr', main).onchange = e => { S.autoAsr = e.target.checked; store.set('autoAsr', S.autoAsr); e.target.parentElement.classList.toggle('on', S.autoAsr); };
  $('#feedStar', main).onclick = () => { S.feedStar = !S.feedStar; pagePlayground(main); };
  renderPanel(main); updateCompose(main); renderFeed(main);
}
function updateCompose(main) {
  $('#count', main).textContent = `${[...S.text].length} 字`;
  const slots = [slot()], bad = slots.find(s => !usable(M(s.model)));
  const design = slots.find(s => M(s.model).caps.design && !s.instructions.trim());
  const bm = bad && M(bad.model), cloudBad = bm && bm.provider !== 'local';
  const hint = !S.text.trim() ? '先输入文字' : bad ? (cloudBad ? `${PV(bm.provider)?.name || bm.provider} 还没连接` : `${bm.name} 还没下载`) : design ? '声音设计模型需要先写声音描述' : '';
  const cost = !hint ? slots.map(s => estimateLocal(reqOf(s))).filter(Boolean) : [];
  $('#hint', main).innerHTML = bad && S.text.trim() ? `${esc(hint)} · <a href="#/models/${cloudBad ? bm.provider : 'local'}">${cloudBad ? '去连接' : '去下载'}</a>` : hint ? esc(hint) : cost.length ? `预估 ${cost.map(esc).join(' + ')}` : '';
  $('#gen', main).disabled = !!hint;
  renderEquiv(main);
}
function renderEquiv(main) {
  const r = reqOf(slot()), tabs = { cli: 'CLI', curl: 'cURL', python: 'Python（OpenAI SDK）' };
  $('#equiv', main).innerHTML = `<div class="equiv-head"><span>等价调用</span>
    <div class="seg">${Object.entries(tabs).map(([k, t]) => `<button type="button" data-eq="${k}" class="${S.equiv === k ? 'on' : ''}">${t}</button>`).join('')}</div><span class="sp"></span>
    <button class="btn ghost sm" type="button" id="eqCopy">复制</button></div><pre>${esc(cmdOf(r, S.equiv))}</pre>`;
  $$('[data-eq]', main).forEach(b => b.onclick = () => { S.equiv = b.dataset.eq; store.set('equiv', S.equiv); renderEquiv(main); });
  $('#eqCopy', main).onclick = () => copy(cmdOf(reqOf(slot()), S.equiv), '已复制，可直接在终端或脚本里运行');
}
function renderPanel(main) {
  const p = $('#panel', main), s = slot(), m = M(s.model), has = k => m.params.includes(k), c = m.caps;
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'preset'), my = S.voices.filter(v => v.kind === 'custom');
  const ex = m.instr_examples || (c.design ? S.cat.design : S.cat.instructions);
  p.style.setProperty('--m', hue(m.id));
  p.innerHTML = `
    <div class="field"><div class="lbl"><span>模型</span><span class="key">model</span></div>
      <select class="in" id="pModel">${[...new Set(S.models.filter(x => x.mine || x.id === m.id).map(x => x.provider))].map(pid => `<optgroup label="${pid === 'local' ? '本地' : esc(PV(pid)?.name || pid)}">${S.models.filter(x => x.provider === pid && (x.mine || x.id === m.id)).map(x => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.name)}${usable(x) ? '' : ` · ${STATUS[x.status]}`}</option>`).join('')}</optgroup>`).join('')}</select>
      <div class="cap">${[['voices', '预置音色'], ['instructions', '情绪指令'], ['design', '声音设计'], ['seed', '可复现']].map(([k, t]) => `<span class="${c[k] ? 'y' : 'n'}">${t}</span>`).join('')}</div>
      ${usable(m) ? '' : m.provider !== 'local' ? `<div class="err">${esc(PV(m.provider)?.name || m.provider)} 还没连接。<a href="#/models/${m.provider}">去填 Key</a>，或运行 <code>vox keys set ${esc(m.key_env)}</code></div>` : `<div class="err">模型还没下载。<a href="#/models/local">去模型页下载</a>，或运行 <code>vox models add ${esc(short(m))}</code></div>`}
      ${m.price ? `<span style="font-size:12px;color:var(--mute)">${m.provider === 'local' ? '' : '计费：' + priceText(m)}</span>` : ''}</div>
    ${my.length ? `<div class="field"><div class="lbl"><span>从我的音色载入</span></div><select class="in" id="pMy"><option value="">选择…</option>${my.map(v => `<option value="${esc(v.ref)}">${esc(v.name)}</option>`).join('')}</select></div>` : ''}
    ${has('voice') ? `<div class="field"><div class="lbl"><span>音色</span><span class="key">voice</span></div>
      <div class="vrow"><select class="in" id="pVoice">${vs.map(v => `<option value="${esc(v.voice)}" ${v.voice === s.voice ? 'selected' : ''}>${esc(v.name)}${v.gender ? ` · ${v.gender}` : ''}${v.lang && v.lang !== '中文' ? ` · ${esc(v.lang)}` : ''}</option>`).join('')}</select>
      <button class="pb" type="button" id="pPreview" data-url="${esc(vs.find(v => v.voice === s.voice)?.sample.url || '')}" ${usable(m) ? '' : 'disabled'} title="试听这个音色的样本" aria-label="试听音色样本">${ic('play', 13)}</button></div>
      <span style="font-size:12px;color:var(--mute)">${esc(vs.find(v => v.voice === s.voice)?.description || '')}</span></div>` : ''}
    ${has('instructions') ? `<div class="field"><div class="lbl"><span>${c.design ? '声音描述（必填）' : '情绪 / 语气'}</span><span class="key">instructions</span></div>
      <textarea class="in" id="pInstr" rows="2" placeholder="${c.design ? '例如：三十岁左右的男声，温和真诚' : m.instr_enum ? '只能选下面的情绪之一' : m.provider === 'inworld' ? '必须用英文，例如 speak warmly and slowly' : '留空为自然语气；例如：轻快友好'}">${esc(s.instructions)}</textarea>
      <div class="chips">${ex.map(t => `<button type="button" class="chip ${t === s.instructions ? 'on' : ''}" data-ex="${esc(t)}">${esc(t.length > 12 ? t.slice(0, 12) + '…' : t)}</button>`).join('')}</div></div>` : ''}
    <div class="field"><div class="lbl"><span>语速 <span class="val" id="vSpeed">${Number(s.speed).toFixed(2)}×</span></span><span class="key">speed</span></div>
      <input type="range" id="pSpeed" min="0.5" max="2" step="0.05" value="${s.speed}" aria-label="语速"></div>
    ${has('seed') ? `<div class="field"><div class="lbl"><span>随机种子</span><span class="key">seed</span></div>
      <div class="seedrow"><div class="seg"><button type="button" data-sm="random" class="${s.seedMode === 'random' ? 'on' : ''}">每次随机</button><button type="button" data-sm="fixed" class="${s.seedMode === 'fixed' ? 'on' : ''}">固定</button></div>
      ${s.seedMode === 'fixed' ? `<input class="in mono" type="number" id="pSeed" value="${s.seed}" min="0" aria-label="种子">` : ''}</div>
      <span style="font-size:12px;color:var(--mute)">${s.seedMode === 'fixed' ? '同样的参数和种子，会生成同一版声音。' : '每次生成都会换一版，结果里会记下用了哪个种子。'}</span></div>` : ''}
    ${has('lang') || has('temperature') ? `<details class="adv"><summary>更多设置</summary>
      ${has('lang') ? `<div class="field"><div class="lbl"><span>语言</span><span class="key">lang</span></div><select class="in" id="pLang">${LANGS.map(l => `<option ${l === s.lang ? 'selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}
      ${has('temperature') ? [['temperature', 0.1, 1.5, 0.05], ['top_p', 0.1, 1, 0.05], ['top_k', 1, 100, 1], ['repetition_penalty', 1, 1.5, 0.01]].map(([k, a, b, st]) => `<div class="field"><div class="lbl"><span>${k} <span class="val" data-v="${k}">${s[k]}</span></span></div><input type="range" data-gen="${k}" min="${a}" max="${b}" step="${st}" value="${s[k]}"></div>`).join('') + '<button class="btn ghost sm" type="button" id="genReset">恢复默认采样参数</button>' : ''}
    </details>` : ''}
    <button class="btn" type="button" id="saveMy">存为我的音色</button>`;
  const upd = () => { saveSlots(); updateCompose(main); };
  const redraw = () => { saveSlots(); renderPanel(main); updateCompose(main); };
  $('#pModel', p).onchange = e => { Object.assign(s, newSlot({ model: e.target.value })); redraw(); };
  const pmy = $('#pMy', p); if (pmy) pmy.onchange = e => { const v = S.voices.find(x => x.ref === e.target.value); if (v) { Object.assign(s, newSlot(v.request)); redraw(); toast(`已载入「${v.name}」`); } };
  const pv = $('#pVoice', p); if (pv) pv.onchange = e => { s.voice = e.target.value; redraw(); };
  const pp = $('#pPreview', p); if (pp) pp.onclick = () => playSample(`${short(m)}:${s.voice}`, pp);
  const pi = $('#pInstr', p); if (pi) pi.oninput = e => { s.instructions = e.target.value; $$('[data-ex]', p).forEach(b => b.classList.toggle('on', b.dataset.ex === s.instructions)); upd(); };
  $$('[data-ex]', p).forEach(b => b.onclick = () => { s.instructions = s.instructions === b.dataset.ex ? '' : b.dataset.ex; pi.value = s.instructions; $$('[data-ex]', p).forEach(x => x.classList.toggle('on', x.dataset.ex === s.instructions)); upd(); });
  $('#pSpeed', p).oninput = e => { s.speed = +e.target.value; $('#vSpeed', p).textContent = s.speed.toFixed(2) + '×'; upd(); };
  $$('[data-sm]', p).forEach(b => b.onclick = () => { s.seedMode = b.dataset.sm; redraw(); });
  const ps = $('#pSeed', p); if (ps) ps.oninput = e => { s.seed = +e.target.value; upd(); };
  const pl = $('#pLang', p); if (pl) pl.onchange = e => { s.lang = e.target.value; upd(); };
  $$('[data-gen]', p).forEach(r => r.oninput = () => { s[r.dataset.gen] = +r.value; $(`[data-v="${r.dataset.gen}"]`, p).textContent = r.value; upd(); });
  const gr = $('#genReset', p); if (gr) gr.onclick = () => { Object.assign(s, GEN_DEFAULT); redraw(); };
  $('#saveMy', p).onclick = () => saveMyVoice(reqOf(s, ''), m);
}
async function saveMyVoice(r, m) {
  delete r.input;
  const base = r.voice ? voiceName(r.model, r.voice) : '设计音色', name = `${base}${r.instructions ? ' · ' + r.instructions.slice(0, 10) : ''}`;
  if (M(r.model).caps.seed && r.seed == null) toast('提示：当前是「每次随机」种子，存下的音色每次听起来会略有不同。固定一个满意的种子再存更稳。', 5000);
  const rec = await api('/api/my-voices', { name, request: r });
  await refreshVoices(); toast(`已存为「${rec.name}」，在音色库的「我的」里`);
}

async function generate(main) {
  if ($('#gen', main).disabled) return;
  const text = S.text.trim();
  const run = { id: Date.now(), text, ts: Date.now(), takes: [{ label: '', req: reqOf(slot(), text), rec: null, err: null }] };
  S.runs.unshift(run); renderFeed(main);
  const btn = $('#gen', main); btn.disabled = true;
  for (const t of run.takes) {
    const m = M(t.req.model); t.pending = m.status === 'loaded' ? '生成中…' : `生成中… 首次使用 ${m.name} 需要先加载模型（十几秒）`;
    renderFeed(main);
    try { t.rec = await api('/api/speech', { ...t.req, source: 'webui' }); S.hist = [t.rec, ...S.hist.filter(h => h.id !== t.rec.id)]; }
    catch (e) { t.err = e.message; }
    t.pending = null; renderFeed(main);
    if (m.status !== 'loaded') { refreshModels(); refreshStatus(); }
    if (t.rec && S.autoAsr && S.status?.asr && !t.rec.asr) runAsr(t.rec.id, main);
  }
  updateCompose(main);
}
function renderFeed(main) {
  const feed = $('#feed', main); if (!feed) return;
  const seen = new Set(S.runs.flatMap(r => r.takes.map(t => t.rec?.id)));
  const runs = [...S.runs, ...S.hist.filter(h => !seen.has(h.id)).slice(0, 40).map(h => ({ id: h.id, text: h.request.input, ts: h.ts * 1000, takes: [{ label: '', req: h.request, rec: h }] }))]
    .filter(r => !S.feedStar || r.takes.some(t => t.rec?.star));
  feed.innerHTML = runs.length ? runs.map(runHtml).join('') : `<div class="empty"><b>${S.feedStar ? '还没有收藏的结果' : '还没有生成过'}</b>${S.feedStar ? '点结果上的「收藏」。' : '在上面输入一句话，按 ⌘↵ 生成；或者先去<a href="#/voices">音色库</a>挑一个声音。'}</div>`;
  $$('canvas.wave', feed).forEach(cv => drawWave(cv, cv.dataset.url));
  feed.onclick = e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const id = b.dataset.id, rec = S.hist.find(h => h.id === id) || S.runs.flatMap(r => r.takes).find(t => t.rec?.id === id)?.rec;
    const act = b.dataset.act;
    if (act === 'play') play(`/clips/${id}.wav`, { title: rec.request.input.slice(0, 40), sub: `${short(M(rec.request.model))} · ${voiceName(rec.request.model, rec.request.voice) || '设计'}${rec.request.seed != null ? ' · 种子 ' + rec.request.seed : ''}`, color: hue(rec.request.model) });
    if (act === 'star') { rec.star = !rec.star; api('/api/history/update', { id, star: rec.star }); renderFeed(main); }
    if (act === 'asr') runAsr(id, main);
    if (act === 'reuse') { Object.assign(slot(), newSlot(rec.request)); if (rec.request.seed != null) slot().seedMode = 'fixed'; S.text = rec.request.input; store.set('text', S.text); saveSlots(); pagePlayground(main); toast('已套用这条的全部参数（含种子）'); scrollTo({ top: 0, behavior: 'smooth' }); }
    if (act === 'save') saveMyVoice({ ...rec.request }, M(rec.request.model));
    if (act === 'cmd') copy(cmdOf(rec.request, 'cli'), '已复制 CLI 命令');
  };
  feed.ondblclick = null;
  $$('canvas.wave', feed).forEach(cv => cv.onclick = e => { const r = cv.getBoundingClientRect(), id = cv.dataset.id, rec = S.hist.find(h => h.id === id);
    play(cv.dataset.url, { title: rec?.request.input.slice(0, 40) || '', sub: rec ? short(M(rec.request.model)) : '', color: rec ? hue(rec.request.model) : '' }, (e.clientX - r.left) / r.width); });
}
function runHtml(run) {
  const d = new Date(run.ts), time = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return `<div class="run"><div class="run-text"><span>${esc(run.text)}</span><time>${time}</time></div><div class="takes">${run.takes.map(takeHtml).join('')}</div></div>`;
}
function takeHtml(t) {
  const r = t.rec?.request || t.req, m = M(r.model), head = `<div class="take-h">${t.label ? `<b class="mono">${t.label}</b>` : ''}<span class="mtag">${m && m.provider !== 'local' ? pIcon(m.provider) : '<i class="dot"></i>'}${esc(m?.name || r.model)}</span>${r.voice ? `<b>${esc(voiceName(r.model, r.voice))}</b>` : ''}${r.instructions ? `<span class="instr">「${esc(r.instructions)}」</span>` : ''}</div>`;
  if (t.err) return `<div class="take" style="--m:${hue(r.model)}">${head}<div class="err">生成失败：${esc(t.err)}</div></div>`;
  if (!t.rec) return `<div class="take pending" style="--m:${hue(r.model)}">${head}<span>${esc(t.pending || '排队中…')}</span></div>`;
  const h = t.rec, url = `/clips/${h.id}.wav`, rtf = h.elapsed / Math.max(h.dur, 0.01);
  return `<div class="take" style="--m:${hue(r.model)}">${head}
    <div class="take-w"><button class="pb" type="button" data-act="play" data-id="${h.id}" data-url="${url}" aria-label="播放">${ic('play', 13)}</button><canvas class="wave" data-url="${url}" data-id="${h.id}"></canvas></div>
    <div class="meta"><span><b>${h.dur.toFixed(2)}s</b></span><span>合成 ${h.elapsed}s</span><span title="合成耗时 ÷ 音频时长，小于 1 表示比实时快">RTF ${rtf.toFixed(2)}</span>${r.speed ? `<span>${r.speed}×</span>` : ''}${r.seed != null ? `<span>种子 ${r.seed}</span>` : ''}${h.cached ? '<span>缓存</span>' : ''}${h.source && h.source !== 'webui' ? `<span>来自 ${esc(h.source)}</span>` : ''}${h.cost?.amount != null ? `<span title="${esc(h.cost.text)}">${h.cost.currency === 'CNY' ? '¥' : '$'}${h.cost.amount.toFixed(4)}</span>` : ''}${h.reproducible === false ? '<span title="这家 Provider 不支持随机种子，同样参数再生成可能不同">不可复现</span>' : ''}</div>
    <div class="asr" id="asr-${h.id}">${asrHtml(h)}</div>
    <div class="acts">
      <button class="btn ghost sm fav ${h.star ? 'on' : ''}" type="button" data-act="star" data-id="${h.id}" aria-pressed="${!!h.star}">${ic('star', 14)}${h.star ? '已收藏' : '收藏'}</button>
      <button class="btn ghost sm" type="button" data-act="reuse" data-id="${h.id}">用这套参数</button>
      <button class="btn ghost sm" type="button" data-act="save" data-id="${h.id}">存为我的音色</button>
      ${h.asr ? '' : `<button class="btn ghost sm" type="button" data-act="asr" data-id="${h.id}">读音校对</button>`}
      <button class="btn ghost sm" type="button" data-act="cmd" data-id="${h.id}">复制命令</button>
      <a class="btn ghost sm" href="/clips/${h.id}.mp3" download="vox-${h.id}.mp3">下载 mp3</a>
    </div></div>`;
}
/* ============ 试音台 · 对比 ============ */
// 场景：同一段文本，候选之间只差音色、模型或语气。候选纵向排成清单，点播放才生成，生成前给出费用预估。
// 默认所有候选用同一个种子，差别只来自被比较的那一项。
const modeSeg = () => `<div class="seg" role="group" aria-label="模式"><button type="button" data-mode="single" class="${S.compare ? '' : 'on'}">单路</button><button type="button" data-mode="compare" class="${S.compare ? 'on' : ''}">对比</button></div>`;
function bindModeSeg(main) { $$('[data-mode]', main).forEach(b => b.onclick = () => { S.compare = b.dataset.mode === 'compare'; saveSlots(); pagePlayground(main); }); }
const cid = () => Math.random().toString(36).slice(2, 8);
Object.assign(S, { cands: store.get('cands', null), cmpSeed: store.get('cmpSeed', Math.floor(Math.random() * 1e6)), cmpRes: store.get('cmpRes', {}), cmpOpen: null, cmpPick: store.get('cmpPick', null), cmpPicker: false, cmpQ: '' });
const saveCands = () => { store.set('cands', S.cands); store.set('cmpSeed', S.cmpSeed); store.set('cmpPick', S.cmpPick);
  const ks = Object.keys(S.cmpRes); if (ks.length > 300) ks.slice(0, ks.length - 300).forEach(k => delete S.cmpRes[k]); store.set('cmpRes', S.cmpRes); };
function ensureCands() {
  S.cands = (S.cands || []).filter(c => M(c.model));
  if (S.cands.length) return;
  const base = { ...slot(), seedMode: 'shared' }, alt = S.voices.find(v => v.model === base.model && v.kind === 'preset' && v.voice !== base.voice);
  S.cands = [{ ...base, id: cid() }, ...(alt ? [{ ...base, id: cid(), voice: alt.voice }] : [])];
  saveCands();
}
function candReq(c) {
  const r = reqOf(c, S.text.trim());
  if (M(c.model).params.includes('seed') && c.seedMode === 'shared') r.seed = S.cmpSeed;
  return r;
}
const rkey = r => JSON.stringify(Object.keys(r).sort().map(k => [k, r[k]]));
const candRes = c => { const r = candReq(c); return S.cmpRes[rkey(r)]; };
const candLabel = c => { const m = M(c.model); return c.voice && m.caps.voices ? voiceName(m.id, c.voice) : m.caps.design ? '声音设计' : '默认音色'; };

function pageCompare(main) {
  ensureCands();
  main.innerHTML = `
    <div class="head"><div><h1>试音台</h1><p>同一段文本，一次比较多个音色、模型或语气。每行一个候选，只显示和别人不同的地方；点播放才生成。</p></div>${modeSeg()}</div>
    <div class="compose cmp-text">
      <textarea class="in" id="text" aria-label="要合成的文本" placeholder="输入所有候选共用的文本…">${esc(S.text)}</textarea>
      <div class="compose-bar"><div class="chips">${QUICK.map((q, i) => `<button type="button" class="chip" data-quick="${i}">${esc(q.length > 16 ? q.slice(0, 16) + '…' : q)}</button>`).join('')}</div><span class="sp"></span><span class="count" id="count"></span></div>
    </div>
    <section class="sec cmp">
      <div class="sec-h"><h3>候选</h3><span class="n">${S.cands.length}</span>
        <span class="note seedline">统一种子 <code class="mono">${S.cmpSeed}</code><button class="btn ghost sm" type="button" id="reseed" title="换一个统一种子（只影响支持种子的模型）">${ic('dice', 14)}换一个</button></span>
        <span class="sp"></span><span class="note" id="cmpEst"></span><button class="btn primary sm" type="button" id="genAll"></button></div>
      <div class="clist" id="clist"></div>
      <div class="cmp-add"><button class="btn sm" type="button" id="addDup">${ic('dup', 14)}复制最后一个候选</button><button class="btn sm" type="button" id="addVoices">${ic('plus', 14)}按音色添加…</button>
        <span class="note">选音色：用「按音色添加」一次加几个；调语气：复制一个候选再改语气。</span></div>
      <div id="picker"></div>
    </section>
    <div id="pickbar"></div>`;
  const ta = $('#text', main);
  onText(ta, () => { S.text = ta.value; store.set('text', S.text); refreshRows(main); }, 150);
  $$('[data-quick]', main).forEach(b => b.onclick = () => { ta.value = S.text = QUICK[+b.dataset.quick]; store.set('text', S.text); renderCands(main); });
  bindModeSeg(main);
  $('#reseed', main).onclick = () => { S.cmpSeed = Math.floor(Math.random() * 1e6); saveCands(); pageCompare(main); };
  $('#genAll', main).onclick = () => genAll(main);
  $('#addDup', main).onclick = () => { const last = S.cands[S.cands.length - 1]; const c = { ...last, id: cid() }; S.cands.push(c); S.cmpOpen = c.id; saveCands(); renderCands(main); };
  $('#addVoices', main).onclick = () => { S.cmpPicker = !S.cmpPicker; renderPicker(main); };
  renderCands(main); renderPicker(main);
}
function renderCands(main) {
  const list = $('#clist', main); if (!list) return;
  list.innerHTML = S.cands.map(candRow).join('');
  $$('canvas.wave', list).forEach(cv => drawWave(cv, cv.dataset.url));
  renderCmpHead(main); bindCands(main); renderPickbar(main);
}
// 只重绘每行的摘要（音色、语气、结果），展开的编辑区原样保留：打字时不打断输入法、不丢光标
function refreshRows(main) {
  const list = $('#clist', main); if (!list) return;
  $$('.cand', list).forEach((el, i) => {
    const c = S.cands[i]; if (!c) return;
    const tmp = document.createElement('div'); tmp.innerHTML = candRow(c, i);
    const fresh = tmp.firstElementChild;
    el.replaceChild(fresh.querySelector('.cr'), el.querySelector('.cr'));
    el.className = fresh.className; el.style.cssText = fresh.style.cssText;
    $$('canvas.wave', el).forEach(cv => drawWave(cv, cv.dataset.url));
  });
  renderCmpHead(main); bindCands(main); renderPickbar(main);
}
function renderCmpHead(main) {
  $('#count', main).textContent = `${[...S.text].length} 字`;
  // 预估：只算还没生成、能生成的候选
  const todo = S.text.trim() ? S.cands.filter(c => usable(M(c.model)) && !candRes(c)?.rec && !candRes(c)?.busy) : [];
  const ests = todo.map(c => estimateNum(candReq(c))).filter(Boolean), sum = {};
  ests.filter(e => !e.token).forEach(e => sum[e.cur] = (sum[e.cur] || 0) + e.v);
  const tok = ests.filter(e => e.token).length, cost = Object.entries(sum).map(([cur, v]) => money(v, cur));
  $('#cmpEst', main).textContent = !S.text.trim() ? '先输入文本' : todo.length ? `${todo.length} 条未生成${cost.length ? ` · 云端约 ${cost.join(' + ')}` : todo.some(c => M(c.model).provider !== 'local') ? '' : ' · 都是本地模型，免费'}${tok ? ` · ${tok} 条按 token 计费` : ''}` : '都已生成';
  const g = $('#genAll', main); g.hidden = !todo.length; g.innerHTML = `生成 ${todo.length} 条`;
}
function candRow(c, i) {
  const m = M(c.model), r = candReq(c), res = S.cmpRes[rkey(r)], open = S.cmpOpen === c.id, ok = usable(m) && S.text.trim();
  const tone = m.caps.instructions ? (r.instructions ? `「${r.instructions}」` : m.caps.design ? '（还没写声音描述）' : '自然语气') : '';
  const seed = m.params.includes('seed') ? (c.seedMode === 'random' ? '随机种子' : c.seedMode === 'fixed' ? `种子 ${c.seed}` : '') : '不可复现';
  const bits = [tone, r.speed ? `${r.speed}×` : '', seed].filter(Boolean);
  const est = estimateNum(r);
  const state = !usable(m) ? `<span class="err">${m.provider === 'local' ? '模型还没下载' : `${esc(PV(m.provider)?.name || '')} 还没连接`}</span>`
    : res?.busy ? '<span class="note">生成中…</span>'
    : res?.err ? `<span class="err" title="${esc(res.err)}">生成失败：${esc(res.err)}</span>`
    : res?.rec ? `<canvas class="wave" data-url="/clips/${res.rec.id}.wav" data-id="${res.rec.id}" data-c="${c.id}"></canvas><span class="cr-meta">${res.rec.dur.toFixed(1)}s${res.rec.cost?.amount != null ? ` · ${money(res.rec.cost.amount, res.rec.cost.currency)}` : ''}</span>`
    : `<span class="note">${S.text.trim() ? `点播放生成${est ? est.token ? ' · 按 token 计费' : ` · 约 ${money(est.v, est.cur)}` : ' · 本地免费'}` : '先输入文本'}</span>`;
  return `<div class="cand ${open ? 'open' : ''} ${S.cmpPick === c.id ? 'pick' : ''}" style="--m:${hue(m.id)}">
    <div class="cr">
      <span class="cr-l">${LETTER(i)}</span>
      <button class="pb ${res?.busy ? 'busy' : ''}" type="button" data-cplay="${c.id}" ${res?.rec ? `data-url="/clips/${res.rec.id}.wav"` : ''} ${ok && !res?.busy ? '' : 'disabled'} aria-label="${res?.rec ? '播放' : '生成并播放'} ${LETTER(i)}">${res?.busy ? '' : ic('play', 14)}</button>
      <button class="cr-who" type="button" data-cedit="${c.id}" aria-expanded="${open}"><b>${esc(candLabel(c))}</b><span>${m.provider === 'local' ? '<i class="dot"></i>' : pIcon(m.provider, 13)}<em title="${esc(m.name)}">${esc(m.name)}</em></span></button>
      <button class="cr-diff" type="button" data-cedit="${c.id}" aria-label="编辑候选 ${LETTER(i)}">${bits.map(b => `<span>${esc(b)}</span>`).join('')}${ic('edit', 13)}</button>
      <div class="cr-res">${state}</div>
      <div class="cr-a">
        <button class="btn ghost sm fav ${S.cmpPick === c.id ? 'on' : ''}" type="button" data-cpick="${c.id}" aria-pressed="${S.cmpPick === c.id}" title="选中这个候选">${ic('star', 14)}${S.cmpPick === c.id ? '已选' : '选它'}</button>
        <button class="btn ghost sm" type="button" data-cdel="${c.id}" ${S.cands.length < 2 ? 'disabled' : ''} title="移除这个候选" aria-label="移除候选 ${LETTER(i)}">${ic('x', 14)}</button>
      </div>
    </div>
    ${open ? candEditor(c) : ''}
  </div>`;
}
function candEditor(c) {
  const m = M(c.model), has = k => m.params.includes(k), c2 = m.caps;
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'preset'), ex = m.instr_examples || (c2.design ? S.cat.design : S.cat.instructions);
  return `<div class="ced" data-ced="${c.id}">
    <div class="field"><div class="lbl"><span>模型</span><span class="key">model</span></div>
      <select class="in" data-f="model">${[...new Set(mine().map(x => x.provider))].map(pid => `<optgroup label="${pid === 'local' ? '本地' : esc(PV(pid)?.name || pid)}">${mine().filter(x => x.provider === pid).map(x => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</optgroup>`).join('')}</select></div>
    ${has('voice') ? `<div class="field"><div class="lbl"><span>音色</span><span class="key">voice</span></div>
      <div class="vrow"><select class="in" data-f="voice">${vs.map(v => `<option value="${esc(v.voice)}" ${v.voice === c.voice ? 'selected' : ''}>${esc(v.name)}${v.gender ? ` · ${v.gender}` : ''}${v.lang && v.lang !== '中文' ? ` · ${esc(v.lang)}` : ''}</option>`).join('')}</select>
      <button class="pb" type="button" data-sample="${esc(short(m))}:${esc(c.voice)}" data-url="${esc(vs.find(v => v.voice === c.voice)?.sample.url || '')}" title="试听音色样本" aria-label="试听音色样本">${ic('play', 13)}</button></div></div>` : ''}
    ${has('instructions') ? `<div class="field wide"><div class="lbl"><span>${c2.design ? '声音描述' : '情绪 / 语气'}</span><span class="key">instructions</span></div>
      <input class="in" data-f="instructions" value="${esc(c.instructions)}" placeholder="${c2.design ? '例如：三十岁左右的男声，温和真诚' : m.instr_enum ? '只能选下面的情绪之一' : '留空为自然语气'}">
      <div class="chips">${ex.slice(0, 8).map(t => `<button type="button" class="chip ${t === c.instructions ? 'on' : ''}" data-ex="${esc(t)}">${esc(t.length > 12 ? t.slice(0, 12) + '…' : t)}</button>`).join('')}</div></div>` : ''}
    <div class="field"><div class="lbl"><span>语速 <span class="val">${Number(c.speed).toFixed(2)}×</span></span><span class="key">speed</span></div>
      <input type="range" data-f="speed" min="0.5" max="2" step="0.05" value="${c.speed}" aria-label="语速"></div>
    ${has('seed') ? `<div class="field"><div class="lbl"><span>种子</span><span class="key">seed</span></div>
      <div class="seedrow"><div class="seg">${[['shared', '统一'], ['fixed', '固定'], ['random', '随机']].map(([k, t]) => `<button type="button" data-sm="${k}" class="${c.seedMode === k ? 'on' : ''}">${t}</button>`).join('')}</div>
      ${c.seedMode === 'fixed' ? `<input class="in mono" type="number" data-f="seed" value="${c.seed}" min="0" aria-label="种子">` : ''}</div></div>` : ''}
    <div class="ced-a"><button class="btn sm" type="button" data-apply="${c.id}" title="把这个候选的语气和语速用到所有候选上">应用语气和语速到全部</button><span class="sp"></span><button class="btn sm" type="button" data-cdone>收起</button></div>
  </div>`;
}
function bindCands(main) {
  const list = $('#clist', main), find = id => S.cands.find(c => c.id === id), redraw = () => { saveCands(); renderCands(main); };
  $$('[data-cedit]', list).forEach(b => b.onclick = () => { S.cmpOpen = S.cmpOpen === b.dataset.cedit ? null : b.dataset.cedit; renderCands(main); });
  $$('[data-cdone]', list).forEach(b => b.onclick = () => { S.cmpOpen = null; renderCands(main); });
  $$('[data-cdel]', list).forEach(b => b.onclick = () => { S.cands = S.cands.filter(c => c.id !== b.dataset.cdel); if (S.cmpPick === b.dataset.cdel) S.cmpPick = null; redraw(); });
  $$('[data-cpick]', list).forEach(b => b.onclick = () => { S.cmpPick = S.cmpPick === b.dataset.cpick ? null : b.dataset.cpick; redraw(); });
  $$('[data-cplay]', list).forEach(b => b.onclick = () => playCand(main, find(b.dataset.cplay)));
  $$('canvas.wave', list).forEach(cv => cv.onclick = e => { const r = cv.getBoundingClientRect(), c = find(cv.dataset.c); play(cv.dataset.url, candMeta(c), (e.clientX - r.left) / r.width); });
  $$('[data-sample]', list).forEach(b => b.onclick = () => playSample(b.dataset.sample, b));
  $$('[data-ced]', list).forEach(ed => {
    const c = find(ed.dataset.ced);
    $$('[data-f]', ed).forEach(inp => {
      const f = inp.dataset.f;
      if (f === 'model') return inp.onchange = () => { Object.assign(c, newSlot({ model: inp.value, instructions: c.instructions, speed: c.speed }), { id: c.id, seedMode: c.seedMode === 'random' ? 'random' : 'shared' }); redraw(); };
      if (f === 'voice') return inp.onchange = () => { c.voice = inp.value; redraw(); };
      if (inp.type === 'range') {
        inp.oninput = () => { $('.val', inp.closest('.field')).textContent = `${(+inp.value).toFixed(2)}×`; };
        return inp.onchange = () => { c.speed = +inp.value; saveCands(); refreshRows(main); };
      }
      // 文本（语气、固定种子）：只改状态和这一行的摘要，不重建正在输入的框
      onText(inp, () => {
        c[f] = f === 'seed' ? +inp.value : inp.value;
        if (f === 'instructions') $$('[data-ex]', ed).forEach(b => b.classList.toggle('on', b.dataset.ex === c.instructions));
        saveCands(); refreshRows(main);
      }, 250);
    });
    $$('[data-ex]', ed).forEach(b => b.onclick = () => { c.instructions = c.instructions === b.dataset.ex ? '' : b.dataset.ex; redraw(); });
    $$('[data-sm]', ed).forEach(b => b.onclick = () => { c.seedMode = b.dataset.sm; redraw(); });
    $$('[data-apply]', ed).forEach(b => b.onclick = () => {
      S.cands.forEach(x => { if (x === c) return; if (M(x.model).params.includes('instructions')) x.instructions = c.instructions; x.speed = c.speed; });
      toast(`已把${c.instructions ? `「${c.instructions}」和 ` : '自然语气和 '}${c.speed}× 语速用到全部候选`); redraw();
    });
  });
}
const candMeta = c => { const r = candReq(c); return { title: `${LETTER(S.cands.indexOf(c))} · ${candLabel(c)}`, sub: `${M(c.model).name}${r.instructions ? ` · ${r.instructions}` : ''}`, color: hue(c.model) }; };
async function genCand(main, c) {
  const r = candReq(c), k = rkey(r);
  if (S.cmpRes[k]?.rec || S.cmpRes[k]?.busy) return S.cmpRes[k];
  S.cmpRes[k] = { busy: true }; renderCands(main);
  try { const rec = await api('/api/speech', { ...r, source: 'webui' }); S.cmpRes[k] = { rec: { id: rec.id, dur: rec.dur, cost: rec.cost, request: rec.request } }; S.hist = [rec, ...S.hist.filter(h => h.id !== rec.id)]; }
  catch (e) { S.cmpRes[k] = { err: e.message }; }
  saveCands(); if (S.route === 'playground' && S.compare) renderCands(main);
  if (M(c.model).status !== 'loaded' && M(c.model).provider === 'local') { refreshModels(); refreshStatus(); }
  return S.cmpRes[k];
}
async function playCand(main, c) {
  const res = candRes(c);
  if (res?.rec) return play(`/clips/${res.rec.id}.wav`, candMeta(c));
  const m = M(c.model); if (m.provider === 'local' && m.status !== 'loaded') toast(`第一次用 ${m.name}，要先加载模型（十几秒）`, 4000);
  const out = await genCand(main, c);
  if (out?.rec && S.route === 'playground' && S.compare) play(`/clips/${out.rec.id}.wav`, candMeta(c));
  else if (out?.err) toast(`生成失败：${out.err}`, 5000);
}
async function genAll(main) {
  const todo = S.cands.filter(c => usable(M(c.model)) && !candRes(c)?.rec);
  for (const c of todo) { if (!(S.route === 'playground' && S.compare)) break; await genCand(main, c); }
}
function renderPicker(main) {
  const el = $('#picker', main); if (!el) return;
  if (!S.cmpPicker) { el.innerHTML = ''; return; }
  const q = S.cmpQ.trim().toLowerCase(), have = new Set(S.cands.map(c => `${c.model}|${c.voice}`));
  const vs = S.voices.filter(v => v.kind === 'preset' && usable(M(v.model)) && (!q || `${v.name} ${v.ref} ${v.description} ${v.lang}`.toLowerCase().includes(q)));
  const ms = [...new Set(vs.map(v => v.model))];
  el.innerHTML = `<div class="vpick">
    <div class="vpick-h"><label class="search">${ic('search', 15)}<input class="in" id="vpq" placeholder="搜索音色名字、描述、语言" value="${esc(S.cmpQ)}" aria-label="搜索音色"></label>
      <span class="note">勾选后添加；语气、语速沿用最后一个候选</span><span class="sp"></span>
      <button class="btn primary sm" type="button" id="vpAdd" disabled>添加</button><button class="btn ghost sm" type="button" id="vpClose">取消</button></div>
    <div class="vpick-l">${ms.map(mid => `<div class="vpick-g"><div class="vpick-gh">${M(mid).provider === 'local' ? `<i class="dot" style="--m:${hue(mid)}"></i>` : pIcon(M(mid).provider, 13)}${esc(M(mid).name)}</div>
      ${(() => { const all = vs.filter(v => v.model === mid); return all.slice(0, 60).map(v => `<label class="vpick-i ${have.has(`${v.model}|${v.voice}`) ? 'has' : ''}"><input type="checkbox" value="${esc(v.ref)}" ${have.has(`${v.model}|${v.voice}`) ? 'disabled checked' : ''}><span><b>${esc(v.name)}</b>${[v.gender && v.gender + '声', v.lang].filter(Boolean).map(esc).join(' · ')}</span></label>`).join('') + (all.length > 60 ? `<span class="note vpick-more">还有 ${all.length - 60} 个，搜索查看</span>` : ''); })()}</div>`).join('') || '<p class="sec-empty">没有匹配的音色。</p>'}</div></div>`;
  const inp = $('#vpq', el); onText(inp, () => { S.cmpQ = inp.value; const pos = inp.selectionStart; renderPicker(main); const n = $('#vpq', main); n.focus(); n.setSelectionRange(pos, pos); }, 150);
  const add = $('#vpAdd', el), boxes = $$('input[type=checkbox]:not([disabled])', el);
  boxes.forEach(b => b.onchange = () => { const n = boxes.filter(x => x.checked).length; add.disabled = !n; add.textContent = n ? `添加 ${n} 个` : '添加'; });
  $('#vpClose', el).onclick = () => { S.cmpPicker = false; renderPicker(main); };
  add.onclick = () => {
    const last = S.cands[S.cands.length - 1];
    boxes.filter(b => b.checked).forEach(b => { const v = S.voices.find(x => x.ref === b.value), m = M(v.model);
      S.cands.push({ ...newSlot({ model: v.model, voice: v.voice }), id: cid(), seedMode: 'shared', speed: last?.speed ?? 1, instructions: m.params.includes('instructions') ? last?.instructions || '' : '' }); });
    S.cmpPicker = false; S.cmpQ = ''; saveCands(); pageCompare(main);
  };
}
function renderPickbar(main) {
  const el = $('#pickbar', main), c = S.cands.find(x => x.id === S.cmpPick); if (!el) return;
  if (!c) { el.innerHTML = ''; return; }
  const r = candReq(c), i = S.cands.indexOf(c);
  el.innerHTML = `<div class="pickbar" style="--m:${hue(c.model)}">${ic('star', 16)}<div><b>选了 ${LETTER(i)} · ${esc(candLabel(c))}</b><span>${esc(M(c.model).name)}${r.instructions ? ` ·「${esc(r.instructions)}」` : ''}${r.speed ? ` · ${r.speed}×` : ''}${r.seed != null ? ` · 种子 ${r.seed}` : ''}</span></div><span class="sp"></span>
    <button class="btn sm" type="button" id="pkCmd">${ic('copy', 14)}复制命令</button><button class="btn sm" type="button" id="pkSave">存为我的音色</button><button class="btn primary sm" type="button" id="pkSingle">在单路里继续调${ic('arrow', 13)}</button></div>`;
  $('#pkCmd', el).onclick = () => copy(cmdOf(r, 'cli'), '已复制 CLI 命令');
  $('#pkSave', el).onclick = () => saveMyVoice({ ...r }, M(r.model));
  $('#pkSingle', el).onclick = () => { Object.assign(slot(), newSlot(r), r.seed != null ? { seedMode: 'fixed', seed: r.seed } : {}); S.compare = false; saveSlots(); pagePlayground(main); scrollTo(0, 0); toast('已带上这个候选的全部参数（含种子）'); };
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
function asrHtml(h) {
  if (h._asrBusy) return '<small>读音校对中…</small>';
  if (!h.asr) return '';
  const { a, hit, score } = asrDiff(h.request.input, h.asr), col = score > .97 ? 'var(--ok)' : score > .85 ? 'var(--warn)' : 'var(--bad)';
  const misses = hit.filter(x => !x).length;
  return `<span class="sc" style="color:${col}">读音 ${Math.round(score * 100)}%</span>${misses ? a.map((c, i) => hit[i] ? esc(c) : `<span class="x">${esc(c)}</span>`).join('') : '<span style="color:var(--text-2)">全部读对</span>'}<small>识别结果：${esc(h.asr)}</small>`;
}
async function runAsr(id, main) {
  const h = S.hist.find(x => x.id === id) || S.runs.flatMap(r => r.takes).find(t => t.rec?.id === id)?.rec; if (!h) return;
  h._asrBusy = true; renderFeed(main);
  try { const r = await api('/api/asr', { id }); h.asr = r.text; } catch (e) { toast(`读音校对失败：${e.message}`, 5000); }
  h._asrBusy = false; renderFeed(main);
}

/* ============ 模型：左侧 Provider，右侧它的模型 ============ */
// 「能不能用」是系统事实（本地下没下载、云端连没连上），不给开关；「我的模型」= 能用的模型里你留下的，音色库和试音台只显示这些。
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
    <div class="head"><div><h1>模型</h1><p>「我的模型」是能直接用的：本地已下载的，和已连接 Provider 里添加的。音色库和试音台只用它们。</p></div>
      <button class="cli" type="button" data-copy="vox models">vox models</button></div>
    <div class="mp">
      <nav class="mp-side" aria-label="Provider">
        <a class="pv ${sub === 'mine' ? 'on' : ''}" href="#/models/mine" ${sub === 'mine' ? 'aria-current="page"' : ''}>${ic('layers', 18)}<span class="pv-n">我的模型</span><span class="pv-c">${mine().length}</span></a>
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
    <div class="pd-h"><span class="pd-ic">${ic('layers', 22)}</span><div><h2>我的模型</h2><p>${my.length ? `${my.length} 个模型可以直接用：本地 ${nl} 个，云端 ${my.length - nl} 个。` : '还没有能直接用的模型。'}</p></div></div>
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
    <section class="sec"><div class="sec-h"><h3>我的模型</h3><span class="n">${my.length}</span></div>
      ${my.length ? `<div class="mlist">${my.map(modelRow).join('')}</div>` : `<p class="sec-empty">${local ? '还没有下载模型。从下面挑一个，下载后完全离线运行。' : !p.connected ? (rec ? `连接后，默认加上 ${rec} 个 vox 核对过的模型；更多模型在下面添加。` : '连接后，从下面添加想用的模型。') : '还没有添加模型。从下面添加。'}</p>`}
    </section>
    <section class="sec"><div class="sec-h"><h3>${local ? '可下载' : '可添加'}</h3><span class="n">${avail.length}</span><span class="sp"></span><span class="note">${note}</span>
      ${d ? `<button class="btn sm" type="button" id="dFetch" ${canFetch && !busy ? '' : 'disabled'} ${canFetch ? '' : 'title="先连接（填 Key）"'}>${ic('refresh', 14, busy ? 'spin' : '')}${busy ? '查询中' : d.fetched ? '刷新' : '在线查询'}</button>` : ''}</div>
      ${err ? `<div class="err">${esc(err)}</div>` : ''}
      ${avail.length > 8 ? `<label class="search">${ic('search', 15)}<input class="in" id="mq" placeholder="筛选 ${avail.length} 个模型" value="${esc(S.mq[p.id] || '')}" aria-label="筛选模型"></label>` : ''}
      ${shown.length ? `<div class="mlist">${shown.map(modelRow).join('')}</div>` : `<p class="sec-empty">${busy ? '正在查询…' : q ? '没有匹配的模型。' : avail.length ? '' : '都已在我的模型里。'}</p>`}
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
        <div class="field"><div class="lbl"><span>名称</span></div><input class="in" name="name" value="${esc(c.name || '')}" placeholder="例如：我的 Kokoro" required></div>
        <div class="field"><div class="lbl"><span>ID</span><span class="key">命令行和模型 ID 里用</span></div><input class="in mono" name="id" value="${esc(pid)}" placeholder="my-kokoro" ${editing ? 'disabled' : ''} pattern="[a-z0-9][a-z0-9-]{1,31}" required></div>
        <div class="field"><div class="lbl"><span>类型</span></div><select class="in" name="type"><option value="openai">OpenAI 兼容</option></select></div>
        <div class="field wide"><div class="lbl"><span>Base URL</span><span class="key">到 /v1 为止</span></div><input class="in mono" name="base_url" value="${esc(c.base_url || '')}" placeholder="http://127.0.0.1:8880/v1" required spellcheck="false"></div>
        <div class="field wide"><div class="lbl"><span>API Key</span></div>
          <div class="pf-key"><div class="seg" role="group" aria-label="是否需要 Key"><button type="button" data-auth="1" class="${c.auth ? 'on' : ''}">需要</button><button type="button" data-auth="0" class="${c.auth ? '' : 'on'}">不需要（本机自建常见）</button></div>
          ${c.auth ? `<input class="in mono" name="key" type="password" placeholder="${editing && p.connected ? '已保存；粘贴新值以替换' : '粘贴 Key（也可以之后再填）'}" spellcheck="false">` : ''}</div></div>
      </div>
      <details class="adv" ${editing ? 'open' : ''}><summary>兼容选项</summary>
        <div class="pf-grid">
          <div class="field"><div class="lbl"><span>情绪指令怎么传</span><span class="key">instructions</span></div>
            <select class="in" name="instructions">${[['instructions', 'instructions 字段（OpenAI 写法）'], ['instruction', 'instruction 字段'], ['prefix', '写进正文：指令<|endofprompt|>正文'], ['none', '不支持']].map(([k, t]) => `<option value="${k}" ${c.instructions === k ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
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
  return m.status === 'loaded' ? '<span class="pill loaded">已加载</span>' : m.status === 'downloading' ? '<span class="pill downloading">下载中</span>' : '';
}
function modelRow(m) {
  const cloud = m.provider !== 'local';
  const params = m.params_b ? (m.params_b >= 1 ? `${m.params_b}B` : `${Math.round(m.params_b * 1000)}M`) : '';
  const facts = cloud ? [priceText(m) || (m.inferred ? '价格见官网' : ''), m.voice_count ? `${m.voice_count} 个音色` : '']
    : [[params, m.quant].filter(Boolean).join(' · '), m.size_gb ? `${m.size_gb} GB` : '', m.voice_count ? `${m.voice_count} 个音色` : '', m.downloads ? `${fmtN(m.downloads)} 次下载` : ''];
  const caps = [['instructions', m.instr_enum ? '情绪枚举' : '情绪指令'], ['design', '声音设计'], ['seed', '可复现']].filter(([k]) => m.caps[k]).map(([, t]) => t);
  const tags = [m.inferred ? '<span class="tag" title="vox 注册表里没有这个模型：请求格式与能力按同一家已核对的模型推断">能力推断</span>' : '', m.source === 'custom' && cloud ? '<span class="tag">手动添加</span>' : ''].join('');
  return `<div class="mrow ${m.mine ? 'is-mine' : ''}" style="--m:${hue(m.id)}">
    <div class="mr-main">
      <div class="mr-t"><b>${esc(m.name)}</b>${statusPill(m)}${tags}</div>
      <div class="mr-s"><button class="idc" type="button" data-copyid="${esc(m.id)}" title="复制模型 ID">${esc(m.id)}${ic('copy', 12)}</button>${facts.filter(Boolean).map(f => `<span>${f}</span>`).join('')}</div>
      ${m.about ? `<p class="mr-d">${esc(m.about)}</p>` : ''}
      ${caps.length ? `<div class="mr-c">${caps.map(t => `<span>${ic('check', 12)}${t}</span>`).join('')}</div>` : ''}
    </div>
    <div class="mr-a">${rowActions(m)}</div></div>`;
}
function rowActions(m) {
  const cloud = m.provider !== 'local', id = esc(m.id), p = PV(m.provider);
  if (m.status === 'downloading') return `<div class="dl"><span class="note" data-prog="${id}">下载中…</span><div class="bar"><i data-bar="${id}"></i></div></div>`;
  if (m.mine) {
    const tryBtn = `<a class="btn primary sm" href="#/playground" data-trym="${id}">试音</a>`;
    if (cloud) return `${tryBtn}<button class="btn ghost sm" type="button" data-rm="${id}">移除</button>`;
    return `${tryBtn}${m.status === 'loaded' ? `<button class="btn sm" type="button" data-unload="${id}">卸载</button>` : `<button class="btn sm" type="button" data-load="${id}" title="提前载入内存，第一次生成不用等">预加载</button>`}
      <button class="btn ghost sm danger" type="button" data-rm="${id}" data-size="${m.size_gb || ''}">删除</button>`;
  }
  if (!cloud) return m.engine === 'kokoro' ? '<span class="note">首次合成时自动下载</span>' : `<button class="btn sm" type="button" data-add="${id}">${ic('download', 14)}下载${m.size_gb ? ` ${m.size_gb} GB` : ''}</button>`;
  return `<button class="btn sm" type="button" data-add="${id}" ${p?.connected ? '' : 'disabled title="先连接（填 Key）"'}>${ic('plus', 14)}添加</button>`;
}
async function afterModels() { await Promise.all([refreshModels(), api('/api/providers').then(p => S.providers = p)]); await refreshVoices(); }
const rerender = () => { if (S.route === 'models') pageModels($('#main')); };
function bindRows(el) {
  $$('[data-copyid]', el).forEach(b => b.onclick = () => copy(b.dataset.copyid, `已复制 ${b.dataset.copyid}`));
  $$('[data-trym]', el).forEach(a => a.onclick = () => { ensureSlots(); Object.assign(slot(), newSlot({ model: a.dataset.trym })); saveSlots(); });
  $$('[data-add]', el).forEach(b => b.onclick = async () => {
    b.disabled = true; const m = M(b.dataset.add);
    try { await api('/api/models/add', { model: b.dataset.add }); toast(m.provider === 'local' ? `开始下载 ${m.name}` : `已加进我的模型：${m.name}`); }
    catch (e) { b.disabled = false; return toast(e.message, 5000); }
    await afterModels(); rerender();
  });
  $$('[data-rm]', el).forEach(b => b.onclick = async () => {
    const m = M(b.dataset.rm), local = m.provider === 'local';
    if (local && !b.classList.contains('armed')) {   // 删除文件：原地二次确认
      b.classList.add('armed'); b.textContent = `确认删除${b.dataset.size ? ` ${b.dataset.size} GB` : ''}`;
      clearTimeout(b._t); b._t = setTimeout(() => { b.classList.remove('armed'); b.textContent = '删除'; }, 4000); return;
    }
    try { await api('/api/models/remove', { model: m.id, delete_files: local }); toast(local ? `已删除 ${m.name} 的模型文件` : `已移出我的模型：${m.name}`); }
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
    toast(`已删除 ${p.name}（它在我的模型里的条目和保存的 Key 一并删除）`, 4000); await afterModels(); location.hash = '#/models/mine';
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
  const sym = p.currency === 'CNY' ? '¥' : '$', per = { 1000: '千', 10000: '万', 1000000: '百万' }[p.per] || p.per;
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
function pageApi(main) {
  const ready = mine().filter(usable), m = M(S.apiModel) && usable(M(S.apiModel)) ? M(S.apiModel) : ready[0] || S.models[0];
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'preset');
  const r = { model: m.id, input: '你好，这是来自 vox 的声音。', ...(m.caps.voices ? { voice: vs[0]?.voice || m.default_voice } : {}), ...(m.caps.design ? { instructions: S.cat.design[1] } : {}) };
  const js = `const res = await fetch("${ORIGIN}/v1/audio/speech", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${JSON.stringify({ ...r, response_format: 'mp3' })}),\n});\nconst audio = new Audio(URL.createObjectURL(await res.blob()));\naudio.play();`;
  const code = { curl: cmdOf(r, 'curl'), python: cmdOf(r, 'python'), js, cli: cmdOf(r, 'cli') };
  const tabs = { curl: 'cURL', python: 'Python', js: 'JavaScript', cli: 'CLI' };
  const eps = [
    ['合成', [['POST', '/v1/audio/speech', 'OpenAI 兼容，返回音频。扩展参数 seed、lang、temperature 等；响应头带 X-Vox-Seed'], ['POST', '/api/speech', '合成并返回 JSON：实际种子、时长、音频地址'], ['GET', '/api/history', '合成历史，与 CLI 共享']]],
    ['模型', [['GET', '/v1/models', 'OpenAI 兼容：我的模型'], ['GET', '/api/models', '全部模型与状态；?mine=1 只看我的，?provider= 只看一家'], ['POST', '/api/models/add · remove', '加进 / 移出我的模型（本地 = 下载 / 删除文件）'],
      ['POST', '/api/providers/discover', '在线查询一家现在提供的模型'], ['POST', '/api/models/load · unload', '预加载 / 卸载本地模型']]],
    ['音色', [['GET', '/api/voices', '音色库，可按 model、lang、gender、q 筛选'], ['POST', '/api/voices/sample', '生成或取音色样本'], ['POST', '/api/asr', '读音校对']]],
    ['给 Agent', [['GET', '/llms.txt', '接口说明与我的模型清单']]]];
  main.innerHTML = `
    <div class="head"><div><h1>API</h1><p>OpenAI 兼容：把客户端的 base URL 换成下面这个，就能调用我的全部模型。</p></div></div>
    <div class="card base-card"><div class="lbl"><span>Base URL</span><span class="key">api_key 随便填，本地服务不校验</span></div>
      <div class="base"><code class="mono">${ORIGIN}/v1</code><button class="btn sm" type="button" data-copy="${ORIGIN}/v1">${ic('copy', 14)}复制</button><a class="lnk" href="/llms.txt" target="_blank">给 Agent 的说明 llms.txt${ic('ext', 13)}</a></div></div>
    <div class="card code-card"><div class="equiv-head"><div class="seg">${Object.entries(tabs).map(([k, t]) => `<button type="button" data-at="${k}" class="${S.apiTab === k ? 'on' : ''}">${t}</button>`).join('')}</div><span class="sp"></span>
      <select class="in sel" id="apiModel" aria-label="示例用的模型">${ready.map(x => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.id)}</option>`).join('')}</select>
      <button class="btn ghost sm" type="button" id="apiCopy">${ic('copy', 14)}复制</button></div><pre>${esc(code[S.apiTab])}</pre></div>
    <div class="card"><table class="ep">${eps.map(([g, rows]) => `<tbody><tr class="ep-g"><th colspan="3">${g}</th></tr>${rows.map(e => `<tr><td class="ep-m">${e[0]}</td><td class="ep-p">${esc(e[1])}</td><td>${esc(e[2])}</td></tr>`).join('')}</tbody>`).join('')}</table></div>
    <div class="card"><div class="lbl"><span>统一的参数名</span></div>
      <table class="ep names"><thead><tr><th></th><th>模型</th><th>音色</th><th>情绪 / 声音描述</th><th>语速</th><th>种子</th></tr></thead>
        <tbody><tr><td class="ep-m">HTTP</td><td><code>model</code></td><td><code>voice</code></td><td><code>instructions</code></td><td><code>speed</code></td><td><code>seed</code></td></tr>
        <tr><td class="ep-m">CLI</td><td><code>-m</code></td><td><code>-v</code></td><td><code>-i</code></td><td><code>-s</code></td><td><code>--seed</code></td></tr></tbody></table>
      <p class="note">音色也可以写引用：<code>qwen3:serena</code>、<code>my:&lt;id&gt;</code>，引用里已经带上了模型。</p></div>`;
  $$('[data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy));
  $$('[data-at]', main).forEach(b => b.onclick = () => { S.apiTab = b.dataset.at; pageApi(main); });
  const am = $('#apiModel', main); if (am) am.onchange = e => { S.apiModel = e.target.value; pageApi(main); };
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
