/* vox WebUI：音色库 / 试音台 / 模型 / API。只调用 vox 的原生 API（/api/*），与 CLI 共用同一套模型、音色、参数。 */
(() => {
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ORIGIN = location.origin;
const GEN_DEFAULT = { temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05 };
const LANGS = ['chinese', 'english', 'japanese', 'korean', 'german', 'french', 'russian', 'portuguese', 'spanish', 'italian', 'auto'];
const STATUS = { loaded: '已加载', ready: '已下载', not_downloaded: '未下载', downloading: '下载中', planned: '即将支持', unavailable: '不可用', needs_key: '需要 Key' };
const STATUS_CLOUD = { ready: '可用' };
const QUICK = ['你好呀，今天过得怎么样？', '我……没问一声，就把 Docker 镜像删了。', '老规矩：先查清，再说明，等你拍板。', 'The quick brown fox jumps over the lazy dog.'];

const store = {
  get(k, d) { try { const v = localStorage.getItem('vox2.' + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('vox2.' + k, JSON.stringify(v)); } catch {} },
};
const S = {
  models: [], voices: [], providers: [], status: null, cat: { instructions: [], design: [] }, settings: { sample_text: '', favorites: [] }, hist: [], myv: [],
  vf: store.get('vf', { q: '', model: 'all', gender: '', lang: '', fav: false }), vlimit: 60,
  slots: store.get('slots', null), cur: 0, compare: store.get('compare', false), text: store.get('text', QUICK[0]),
  runs: [], feedStar: false, equiv: store.get('equiv', 'cli'), apiTab: 'curl', autoAsr: store.get('autoAsr', true),
};

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(typeof j.error === 'string' ? j.error : j.error?.message || `HTTP ${r.status}`);
  return j;
}
function toast(msg, ms = 2400) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), ms); }
async function copy(text, what = '已复制') { try { await navigator.clipboard.writeText(text); toast(what); } catch { toast('复制失败，请手动选择'); } }

/* ---------- 模型工具 ---------- */
const M = id => S.models.find(m => m.id === id || m.alias === id);
const short = m => m?.alias || m?.id;
const hue = id => { const m = M(id); return m?.provider === 'local' ? `var(--${m.alias})` : `var(--p-${m?.provider || 'cloud'}, var(--cloud))`; };
const PV = id => S.providers.find(p => p.id === id);
const MONO = new Set(['openai', 'elevenlabs', 'xiaomimimo']);
const ICON = { local: 'huggingface', openai: 'openai', inworld: null, elevenlabs: 'elevenlabs', gemini: 'gemini', aliyun: 'bailian', volcengine: 'doubao', minimax: 'minimax', stepfun: 'stepfun', siliconflow: 'siliconcloud', mimo: 'xiaomimimo' };
const LETTER_ICON = { inworld: 'In' };
/* Provider 图标：LobeHub Icons（MIT）。单色图标用 CSS mask 跟随主题颜色；缺图标的用字母标。 */
function pIcon(pid, size = 16) {
  const f = ICON[pid];
  if (!f) return `<span class="pic letter" style="--s:${size}px" aria-hidden="true">${esc(LETTER_ICON[pid] || pid.slice(0, 2))}</span>`;
  return MONO.has(f) ? `<span class="pic mono" style="--s:${size}px;--src:url(icons/${f}.svg)" aria-hidden="true"></span>` : `<img class="pic" src="icons/${f}.svg" width="${size}" height="${size}" alt="" aria-hidden="true">`;
}
const usable = m => m && ['ready', 'loaded'].includes(m.status);
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
const fmtT = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
(function loop() {
  const prog = P.a.duration ? P.a.currentTime / P.a.duration : 0, playing = !P.a.paused;
  if (P.url) {
    $('#pPlay').textContent = playing ? '❚❚' : '▶';
    $('#pTime').textContent = `${fmtT(P.a.currentTime || 0)} / ${fmtT(P.a.duration || 0)}`;
    drawWave($('#pWave'), P.url, prog, P.meta?.color && getComputedStyle($('#player')).getPropertyValue('--m'));
    $$('canvas[data-url]').forEach(cv => { if (cv.dataset.url === P.url || cv._p) { drawWave(cv, cv.dataset.url, cv.dataset.url === P.url ? prog : 0); cv._p = cv.dataset.url === P.url; } });
  }
  $$('.pb[data-url]').forEach(b => { if (!b.classList.contains('busy')) b.textContent = b.dataset.url === P.url && playing ? '❚❚' : '▶'; });
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
    <div class="loaded">${s.loaded.length ? s.loaded.map(id => `<div class="lm" style="--m:${hue(id)}"><i class="dot"></i><span>${esc(M(id)?.name || id)}</span><button type="button" data-unload="${esc(id)}" title="从内存卸载">卸载</button></div>`).join('') : '<span>没有模型在内存中</span>'}</div>`;
  $$('[data-unload]', el).forEach(b => b.onclick = async () => { await api('/api/models/unload', { model: b.dataset.unload }); toast('已卸载'); await refreshModels(); refreshStatus(); if (S.route === 'models') render(); });
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
  const main = $('#main'); main.innerHTML = ''; PAGES[S.route](main);
}
window.addEventListener('hashchange', () => { route(); $('#main').focus({ preventScroll: true }); scrollTo(0, 0); });

/* ============ 音色库 ============ */
function filteredVoices(ignoreLang) {
  const f = ignoreLang === true ? { ...S.vf, lang: '' } : S.vf, q = f.q.trim().toLowerCase();
  const okModel = v => { const m = M(v.model); return f.model === 'all' || (f.model === 'my' ? v.kind === 'custom' : f.model === 'ready' ? usable(m) : f.model.startsWith('p:') ? m?.provider === f.model.slice(2) && v.kind === 'preset' : v.model === f.model && v.kind === 'preset'); };
  return S.voices.filter(v => okModel(v)
    && (!f.gender || v.gender === f.gender) && (!f.lang || v.lang === f.lang) && (!f.fav || S.settings.favorites.includes(v.ref))
    && (!q || `${v.ref} ${v.name} ${v.description} ${v.lang}`.toLowerCase().includes(q)));
}
function pageVoices(main) {
  const vs = filteredVoices(), f = S.vf, local = S.models.filter(m => m.enabled && m.provider === 'local' && m.caps.voices);
  const provs = [...new Set(S.models.filter(m => m.enabled && m.provider !== 'local' && m.caps.voices).map(m => m.provider))];
  const nReady = S.voices.filter(v => usable(M(v.model))).length;
  const langs = [...new Set(filteredVoices(true).map(v => v.lang).filter(Boolean))].slice(0, 14);
  const nMy = S.voices.filter(v => v.kind === 'custom').length;
  main.innerHTML = `
    <div class="head"><div><h1>音色库</h1><p>${S.voices.length} 个音色，来自 ${local.length} 个本地模型和 ${provs.length} 家云端 Provider；现在能直接听的有 ${nReady} 个。每个音色读同一段样本，点 ▶ 就听。</p></div>
      <button class="cli" type="button" data-copy="vox voices --json">vox voices --json</button></div>
    <div class="sampleline" id="sampleLine"><span>样本文本</span><q>${esc(S.settings.sample_text)}</q><button class="btn ghost sm" type="button" id="editSample">修改</button></div>
    <div class="filters">
      <input class="in search" id="vq" placeholder="搜索名字、描述、音色 ID…" value="${esc(f.q)}" aria-label="搜索音色">
      <div class="seg" role="group" aria-label="按模型筛选">
        <button type="button" data-fm="all" class="${f.model === 'all' ? 'on' : ''}">全部</button>
        <button type="button" data-fm="ready" class="${f.model === 'ready' ? 'on' : ''}">能直接听 ${nReady}</button>
        <button type="button" data-fm="my" class="${f.model === 'my' ? 'on' : ''}">我的 ${nMy || ''}</button>
      </div>
      <select class="in" id="fprov" style="width:auto" aria-label="按模型或 Provider 筛选"><option value="">按来源…</option>
        <optgroup label="本地">${local.map(m => `<option value="${m.id}" ${f.model === m.id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</optgroup>
        <optgroup label="云端">${provs.map(p => `<option value="p:${p}" ${f.model === 'p:' + p ? 'selected' : ''}>${esc(PV(p)?.name || p)}${PV(p)?.ready ? '' : '（需 Key）'}</option>`).join('')}</optgroup></select>
      <div class="seg" role="group" aria-label="按性别筛选">${[['', '不限'], ['女', '女声'], ['男', '男声']].map(([k, t]) => `<button type="button" data-fg="${k}" class="${f.gender === k ? 'on' : ''}">${t}</button>`).join('')}</div>
      <button type="button" class="chip ${f.fav ? 'on' : ''}" id="ffav">★ 收藏 ${S.settings.favorites.length}</button>
    </div>
    ${langs.length > 1 ? `<div class="chips" style="margin:-4px 0 14px"><button class="chip ${!f.lang ? 'on' : ''}" data-fl="">所有语言</button>${langs.map(l => `<button class="chip ${f.lang === l ? 'on' : ''}" data-fl="${esc(l)}">${esc(l)}</button>`).join('')}</div>` : ''}
    <div class="grid" id="vgrid"></div>
    <div class="more" id="more"></div>`;
  const grid = $('#vgrid', main);
  if (!vs.length) grid.outerHTML = `<div class="empty"><b>${f.model === 'my' ? '还没有自定义音色' : '没有符合条件的音色'}</b>${f.model === 'my' ? '在试音台调好声音后，点「存为我的音色」，就会出现在这里。' : '换个筛选条件试试。'}</div>`;
  else grid.innerHTML = vs.slice(0, S.vlimit).map(voiceCard).join('');
  if (vs.length > S.vlimit) $('#more', main).innerHTML = `<button class="btn" type="button" id="moreBtn">再显示 ${Math.min(60, vs.length - S.vlimit)} 个（共 ${vs.length}）</button>`;
  bindVoices(main, vs);
}
function voiceCard(v) {
  const m = M(v.model), ok = usable(m), fav = S.settings.favorites.includes(v.ref);
  return `<article class="vc" style="--m:${hue(v.model)}" data-ref="${esc(v.ref)}" data-url="${esc(v.sample.url)}">
    <div class="vc-top">
      <button class="pb" type="button" data-sample="${esc(v.ref)}" data-url="${esc(v.sample.url)}" ${ok ? '' : 'disabled'} aria-label="试听 ${esc(v.name)}">▶</button>
      <div class="vc-name"><b>${esc(v.name)}</b><code>${esc(v.ref)}</code></div>
    </div>
    <div class="chips">${v.gender ? `<span class="tag">${v.gender}声</span>` : ''}${v.lang ? `<span class="tag">${esc(v.lang)}</span>` : ''}${v.kind === 'custom' ? '<span class="tag">自定义</span>' : ''}</div>
    <p>${esc(v.description)}</p>
    <canvas class="mini" data-url="${esc(v.sample.url)}" ${v.sample.cached ? '' : 'hidden'}></canvas>
    <div class="vc-foot">
      <span class="mtag">${m && m.provider !== 'local' ? pIcon(m.provider) : '<i class="dot"></i>'}<span>${esc(m?.name || v.model)}</span></span>
      <button class="star ${fav ? 'on' : ''}" type="button" data-fav="${esc(v.ref)}" aria-label="收藏">${fav ? '★' : '☆'}</button>
      ${ok ? `<a class="btn sm" href="#/playground" data-try="${esc(v.ref)}">试音 →</a>` : m?.provider !== 'local' ? `<a class="btn sm" href="#/models/${m?.provider}" data-focus>配置 Key</a>` : `<a class="btn sm" href="#/models/local">先下载模型</a>`}
    </div></article>`;
}
function bindVoices(main, vs) {
  $('#vq', main).oninput = e => { S.vf.q = e.target.value; store.set('vf', S.vf); clearTimeout(S._vq); S._vq = setTimeout(() => { S.vlimit = 60; pageVoices(main); $('#vq', main).focus(); const i = $('#vq', main); i.setSelectionRange(i.value.length, i.value.length); }, 180); };
  $$('[data-fm]', main).forEach(b => b.onclick = () => { S.vf.model = b.dataset.fm; S.vf.lang = ''; S.vlimit = 60; store.set('vf', S.vf); pageVoices(main); });
  $('#fprov', main).onchange = e => { S.vf.model = e.target.value || 'all'; S.vf.lang = ''; S.vlimit = 60; store.set('vf', S.vf); pageVoices(main); };
  $$('[data-focus]', main).forEach(a => a.onclick = () => { S.focusKey = true; });
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
    line.innerHTML = `<span>样本文本</span><input class="in" id="sampleIn" value="${esc(S.settings.sample_text)}"><button class="btn primary sm" type="button" id="saveSample">保存</button><button class="btn ghost sm" type="button" id="cancelSample">取消</button><span style="width:100%;font-size:12px;color:var(--mute)">{name} 会替换成音色名字。改动后，样本在下次试听时按新文本重新生成。</span>`;
    $('#sampleIn', line).focus();
    $('#cancelSample', line).onclick = () => pageVoices(main);
    $('#saveSample', line).onclick = async () => { S.settings = await api('/api/settings', { sample_text: $('#sampleIn', line).value.trim() }); await refreshVoices(); pageVoices(main); toast('样本文本已更新'); };
  };
}
async function playSample(ref, btn) {
  const v = S.voices.find(x => x.ref === ref); if (!v) return;
  const meta = { title: v.name, sub: `${v.ref} · 样本`, color: hue(v.model) };
  if (v.sample.cached) return play(v.sample.url, meta);
  const others = $$(`.pb[data-sample="${CSS.escape(ref)}"]`); others.forEach(b => { b.classList.add('busy'); b.textContent = ''; });
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
  if (btn) { const on = S.settings.favorites.includes(ref); btn.classList.toggle('on', on); btn.textContent = on ? '★' : '☆'; }
  const ff = $('#ffav'); if (ff) ff.textContent = `★ 收藏 ${S.settings.favorites.length}`;
}
const ensureSlots = () => { if (!S.slots || !S.slots.length) S.slots = [newSlot()]; };
function tryVoice(ref) {
  const v = S.voices.find(x => x.ref === ref); if (!v) return;
  ensureSlots(); const s = slot(); Object.assign(s, newSlot(v.request || { model: v.model, voice: v.voice }));
  saveSlots();
}

/* ============ 试音台 ============ */
function newSlot(p = {}) {
  const model = M(p.model)?.id || (S.models.find(m => m.enabled && usable(m) && m.caps.voices) || S.models[0])?.id;
  const m = M(model);
  return { model, voice: p.voice || m?.default_voice || '', instructions: p.instructions || '', speed: p.speed ?? 1, seedMode: p.seed != null ? 'fixed' : 'random',
    seed: p.seed ?? Math.floor(Math.random() * 1e6), lang: p.lang || 'chinese', ...GEN_DEFAULT, ...Object.fromEntries(Object.keys(GEN_DEFAULT).filter(k => p[k] != null).map(k => [k, p[k]])) };
}
const slot = () => S.slots[S.cur] || S.slots[0];
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
  S.slots = S.slots.map(s => M(s.model) ? s : newSlot());
  if (S.cur >= S.slots.length) S.cur = 0;
  const n = S.compare ? S.slots.length : 1;
  main.innerHTML = `
    <div class="head"><div><h1>试音台</h1><p>${S.compare ? `对比模式：${n} 路参数，同一句话，一键生成。` : '写一句话，调好声音，生成。结果会记下完整参数，随时复现。'}</p></div>
      <div class="seg" role="group" aria-label="模式"><button type="button" data-mode="single" class="${S.compare ? '' : 'on'}">单路</button><button type="button" data-mode="compare" class="${S.compare ? 'on' : ''}">A/B 对比</button></div></div>
    <div class="pg">
      <aside class="panel" id="panel" aria-label="参数"></aside>
      <section>
        <div class="compose">
          <textarea class="in" id="text" aria-label="要合成的文本" placeholder="输入要合成的文字…">${esc(S.text)}</textarea>
          <div class="chips">${QUICK.map((q, i) => `<button type="button" class="chip" data-quick="${i}">${esc(q.length > 16 ? q.slice(0, 16) + '…' : q)}</button>`).join('')}</div>
          <div class="compose-bar"><span class="count" id="count"></span><span class="sp"></span><span class="count" id="hint"></span>
            <button class="btn primary lg" type="button" id="gen">生成${n > 1 ? ` ${n} 路` : ''} <kbd style="color:inherit;border-color:currentColor;opacity:.6">⌘↵</kbd></button></div>
        </div>
        <div class="equiv" id="equiv"></div>
        <div class="feed-head"><h2>结果</h2><span class="sp"></span>
          <label class="chip ${S.autoAsr ? 'on' : ''}" style="cursor:pointer"><input type="checkbox" id="autoAsr" ${S.autoAsr ? 'checked' : ''} hidden> 自动读音校对</label>
          <button type="button" class="chip ${S.feedStar ? 'on' : ''}" id="feedStar">★ 只看收藏</button></div>
        <div class="feed" id="feed"></div>
      </section>
    </div>`;
  const ta = $('#text', main);
  ta.oninput = () => { S.text = ta.value; store.set('text', S.text); updateCompose(main); };
  $$('[data-quick]', main).forEach(b => b.onclick = () => { ta.value = S.text = QUICK[+b.dataset.quick]; store.set('text', S.text); updateCompose(main); });
  $$('[data-mode]', main).forEach(b => b.onclick = () => { S.compare = b.dataset.mode === 'compare'; if (S.compare && S.slots.length < 2) S.slots.push({ ...newSlot(slot()), seedMode: 'random' }); if (!S.compare) S.cur = Math.min(S.cur, S.slots.length - 1); saveSlots(); pagePlayground(main); });
  $('#gen', main).onclick = () => generate(main);
  ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); generate(main); } };
  $('#autoAsr', main).onchange = e => { S.autoAsr = e.target.checked; store.set('autoAsr', S.autoAsr); e.target.parentElement.classList.toggle('on', S.autoAsr); };
  $('#feedStar', main).onclick = () => { S.feedStar = !S.feedStar; pagePlayground(main); };
  renderPanel(main); updateCompose(main); renderFeed(main);
}
function updateCompose(main) {
  $('#count', main).textContent = `${[...S.text].length} 字`;
  const slots = S.compare ? S.slots : [slot()], bad = slots.find(s => !usable(M(s.model)));
  const design = slots.find(s => M(s.model).caps.design && !s.instructions.trim());
  const bm = bad && M(bad.model), cloudBad = bm && bm.provider !== 'local';
  const hint = !S.text.trim() ? '先输入文字' : bad ? (cloudBad ? `${PV(bm.provider)?.name || bm.provider} 还没配置 Key` : `${bm.name} 还没下载`) : design ? '声音设计模型需要先写声音描述' : '';
  const cost = !hint ? slots.map(s => estimateLocal(reqOf(s))).filter(Boolean) : [];
  $('#hint', main).innerHTML = bad && S.text.trim() ? `${esc(hint)} · <a href="#/models/${cloudBad ? bm.provider : 'local'}" data-focus>${cloudBad ? '去配置' : '去下载'}</a>` : hint ? esc(hint) : cost.length ? `预估 ${cost.map(esc).join(' + ')}` : '';
  $$('#hint [data-focus]', main).forEach(a => a.onclick = () => { S.focusKey = true; });
  $('#gen', main).disabled = !!hint;
  renderEquiv(main);
}
function renderEquiv(main) {
  const r = reqOf(slot()), tabs = { cli: 'CLI', curl: 'cURL', python: 'Python（OpenAI SDK）' };
  $('#equiv', main).innerHTML = `<div class="equiv-head"><span>等价调用${S.compare ? `（通道 ${LETTER(S.cur)}）` : ''}</span>
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
    ${S.compare ? `<div class="slots">${S.slots.map((x, i) => `<button type="button" class="slot ${i === S.cur ? 'on' : ''}" data-slot="${i}" style="--m:${hue(x.model)}"><i class="dot"></i>${LETTER(i)}</button>`).join('')}
      ${S.slots.length < 6 ? '<button type="button" class="btn ghost sm" id="addSlot">+ 通道</button>' : ''}${S.slots.length > 1 ? `<button type="button" class="btn ghost sm" id="delSlot" style="margin-left:auto">删除 ${LETTER(S.cur)}</button>` : ''}</div>` : ''}
    <div class="field"><div class="lbl"><span>模型</span><span class="key">model</span></div>
      <select class="in" id="pModel">${[...new Set(S.models.filter(x => x.enabled || x.id === m.id).map(x => x.provider))].map(pid => `<optgroup label="${pid === 'local' ? '本地' : esc(PV(pid)?.name || pid)}">${S.models.filter(x => x.provider === pid && (x.enabled || x.id === m.id)).map(x => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.name)}${usable(x) ? '' : ` · ${STATUS[x.status]}`}</option>`).join('')}</optgroup>`).join('')}</select>
      <div class="cap">${[['voices', '预置音色'], ['instructions', '情绪指令'], ['design', '声音设计'], ['seed', '可复现']].map(([k, t]) => `<span class="${c[k] ? 'y' : 'n'}">${t}</span>`).join('')}</div>
      ${usable(m) ? '' : m.provider !== 'local' ? `<div class="err">${esc(PV(m.provider)?.name || m.provider)} 还没配置 Key。<a href="#/models/${m.provider}" data-focus>去配置</a>，或运行 <code>vox keys set ${esc(m.key_env)}</code></div>` : `<div class="err">模型还没下载。<a href="#/models/local">去模型页下载</a>，或运行 <code>vox pull ${esc(short(m))}</code></div>`}
      ${m.price ? `<span style="font-size:12px;color:var(--mute)">${m.provider === 'local' ? '' : '计费：' + priceText(m)}</span>` : ''}</div>
    ${my.length ? `<div class="field"><div class="lbl"><span>从我的音色载入</span></div><select class="in" id="pMy"><option value="">选择…</option>${my.map(v => `<option value="${esc(v.ref)}">${esc(v.name)}</option>`).join('')}</select></div>` : ''}
    ${has('voice') ? `<div class="field"><div class="lbl"><span>音色</span><span class="key">voice</span></div>
      <div class="vrow"><select class="in" id="pVoice">${vs.map(v => `<option value="${esc(v.voice)}" ${v.voice === s.voice ? 'selected' : ''}>${esc(v.name)}${v.gender ? ` · ${v.gender}` : ''}${v.lang && v.lang !== '中文' ? ` · ${esc(v.lang)}` : ''}</option>`).join('')}</select>
      <button class="pb" type="button" id="pPreview" data-url="${esc(vs.find(v => v.voice === s.voice)?.sample.url || '')}" ${usable(m) ? '' : 'disabled'} title="试听这个音色的样本">▶</button></div>
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
  $$('[data-slot]', p).forEach(b => b.onclick = () => { S.cur = +b.dataset.slot; renderPanel(main); renderEquiv(main); });
  const as = $('#addSlot', p); if (as) as.onclick = () => { S.slots.push({ ...newSlot(slot()), seedMode: 'random' }); S.cur = S.slots.length - 1; saveSlots(); pagePlayground(main); };
  const ds = $('#delSlot', p); if (ds) ds.onclick = () => { S.slots.splice(S.cur, 1); S.cur = Math.max(0, S.cur - 1); saveSlots(); pagePlayground(main); };
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
  const text = S.text.trim(), slots = S.compare ? S.slots : [slot()];
  const run = { id: Date.now(), text, ts: Date.now(), takes: slots.map((s, i) => ({ label: S.compare ? LETTER(S.compare ? S.slots.indexOf(s) : i) : '', req: reqOf(s, text), rec: null, err: null })) };
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
  feed.innerHTML = runs.length ? runs.map(runHtml).join('') : `<div class="empty"><b>${S.feedStar ? '还没有收藏的结果' : '还没有生成过'}</b>${S.feedStar ? '点结果上的 ☆ 收藏。' : '在上面输入一句话，按 ⌘↵ 生成；或者先去<a href="#/voices">音色库</a>挑一个声音。'}</div>`;
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
    <div class="take-w"><button class="pb" type="button" data-act="play" data-id="${h.id}" data-url="${url}" aria-label="播放">▶</button><canvas class="wave" data-url="${url}" data-id="${h.id}"></canvas></div>
    <div class="meta"><span><b>${h.dur.toFixed(2)}s</b></span><span>合成 ${h.elapsed}s</span><span title="合成耗时 ÷ 音频时长，小于 1 表示比实时快">RTF ${rtf.toFixed(2)}</span>${r.speed ? `<span>${r.speed}×</span>` : ''}${r.seed != null ? `<span>种子 ${r.seed}</span>` : ''}${h.cached ? '<span>缓存</span>' : ''}${h.source && h.source !== 'webui' ? `<span>来自 ${esc(h.source)}</span>` : ''}${h.cost?.amount != null ? `<span title="${esc(h.cost.text)}">${h.cost.currency === 'CNY' ? '¥' : '$'}${h.cost.amount.toFixed(4)}</span>` : ''}${h.reproducible === false ? '<span title="这家 Provider 不支持随机种子，同样参数再生成可能不同">不可复现</span>' : ''}</div>
    <div class="asr" id="asr-${h.id}">${asrHtml(h)}</div>
    <div class="acts">
      <button class="btn ghost sm" type="button" data-act="star" data-id="${h.id}">${h.star ? '★ 已收藏' : '☆ 收藏'}</button>
      <button class="btn ghost sm" type="button" data-act="reuse" data-id="${h.id}">用这套参数</button>
      <button class="btn ghost sm" type="button" data-act="save" data-id="${h.id}">存为我的音色</button>
      ${h.asr ? '' : `<button class="btn ghost sm" type="button" data-act="asr" data-id="${h.id}">读音校对</button>`}
      <button class="btn ghost sm" type="button" data-act="cmd" data-id="${h.id}">复制命令</button>
      <a class="btn ghost sm" href="/clips/${h.id}.mp3" download="vox-${h.id}.mp3">下载 mp3</a>
    </div></div>`;
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
// Provider 只管连接（Key、地址），模型是清单里的条目：启用后进入音色库和试音台；可以从 Provider 获取更多，或手动添加。
const PSTATE = p => p.id === 'local' ? { cls: 'ok', t: '本机' } : p.ready ? { cls: 'ok', t: '已连接' } : { cls: '', t: '未配置' };
function pageModels(main) {
  const ps = S.providers, pid = PV(S.sub) ? S.sub : (ps.find(p => p.id !== 'local' && p.ready) || ps[0]).id;
  if (S.sub !== pid) history.replaceState(null, '', `#/models/${pid}`);
  S.sub = pid;
  const side = g => ps.filter(p => (p.id === 'local') === (g === 'local')).map(p => { const st = PSTATE(p);
    return `<a class="pv ${p.id === pid ? 'on' : ''}" href="#/models/${p.id}" ${p.id === pid ? 'aria-current="page"' : ''}>${pIcon(p.id, 20)}<span class="pv-n">${esc(p.name)}</span>
      <span class="pv-s"><i class="dot ${st.cls ? 'live' : ''}" title="${st.t}"></i>${p.enabled.length}/${p.models.length}</span></a>`; }).join('');
  main.innerHTML = `
    <div class="head"><div><h1>模型</h1><p>左边选 Provider，右边管理它的模型。启用的模型会出现在音色库和试音台里，所有模型走同一套接口。</p></div>
      <button class="cli" type="button" data-copy="vox models --json">vox models --json</button></div>
    <div class="mp">
      <nav class="mp-side" aria-label="Provider">
        <div class="mp-g">本地</div>${side('local')}
        <div class="mp-g">云端 <span class="count">${ps.filter(p => p.id !== 'local' && p.ready).length}/${ps.length - 1} 已连接</span></div>${side('cloud')}
      </nav>
      <section class="mp-main" id="pd"></section>
    </div>`;
  $('[data-copy]', main).onclick = e => copy(e.currentTarget.dataset.copy, '已复制命令');
  renderProvider($('#pd', main));
  if (S.models.some(m => m.status === 'downloading')) pollPull(main);
}
function renderProvider(el) {
  const p = PV(S.sub), local = p.id === 'local', ms = S.models.filter(m => m.provider === p.id), st = PSTATE(p);
  const disc = S.disc?.pid === p.id ? S.disc : null;
  const listBtn = local ? '' : p.can_list_models
    ? `<button class="btn ${p.ready && !ms.some(m => m.custom) ? 'primary' : ''}" type="button" id="dFetch" ${p.ready ? '' : 'disabled title="先配置 Key"'}>获取模型列表</button>`
    : `<span class="count" title="这家没有公开的模型列表接口">不提供模型列表接口，可手动添加</span>`;
  el.innerHTML = `
    <div class="pd-h">${pIcon(p.id, 36)}<div><h2>${esc(p.name)}</h2><span class="count">${local ? esc(p.about) : `${esc(p.region || '')} · ${ms.length} 个模型`}</span></div>
      <span class="sp"></span><span class="pill ${st.cls ? 'loaded' : 'needs_key'}">${st.t}</span></div>
    ${local ? `<div class="pd-sec"><h3>存储</h3><p class="count">模型下载到 <code>${esc(S.status?.home || '~/.cache/vox')}/models</code>，默认走 ModelScope 镜像，逐个文件按 HuggingFace 哈希校验。Kokoro 首次合成时自动下载。</p></div>` : `
    <div class="pd-sec"><h3>连接 <span class="sp"></span><a href="${esc(p.console)}" target="_blank" rel="noopener">申请 Key ↗</a><a href="${esc(p.docs)}" target="_blank" rel="noopener">API 文档 ↗</a></h3>
      ${p.credentials.map(c => keyField(p, c, false)).join('')}
      ${p.optional.length ? `<details class="adv"><summary>可选设置</summary>${p.optional.map(c => keyField(p, c, true)).join('')}</details>` : ''}
      <details class="adv"><summary>Key 存在哪里？</summary><div class="keynote">两种方式都行，<b>环境变量优先</b>：
        <ul><li><b>在这里粘贴</b>：保存到本机 <code>~/.config/vox/credentials.json</code>（权限 600），立即生效。</li>
        <li><b>环境变量</b>：如 <code>export ${esc(p.credentials[0]?.env)}=…</code>。适合终端、脚本、Agent 和 CI，会覆盖这里保存的值。</li></ul>
        Key 不会通过 API 返回，也不写进日志；页面只显示末 4 位。命令行：<code>vox keys set ${esc(p.credentials[0]?.env)}</code></div></details>
    </div>`}
    <div class="pd-sec"><h3>模型 <span class="count">已启用 ${ms.filter(m => m.enabled).length} / ${ms.length}</span><span class="sp"></span>
      ${listBtn}${local ? '' : `<button class="btn" type="button" id="dAddT">手动添加</button>`}</h3>
      ${local ? '' : `<form class="kform" id="dAdd" ${S.addOpen === p.id ? '' : 'hidden'}><input class="in mono" placeholder="${esc(p.id)} 的模型 ID，如 ${esc(ms[0]?.remote || 'model-name')}" aria-label="模型 ID" spellcheck="false"><button class="btn primary" type="submit">添加</button></form>`}
      ${disc ? discHtml(disc) : ''}
      ${!local && !p.ready ? `<p class="count pd-tip">下面是 vox 预置的模型。配好 Key 后即可使用${p.can_list_models ? '，也可以点「获取模型列表」看看这家现在还提供哪些' : ''}。</p>` : ''}
      <div class="mlist">${ms.map(modelCard).join('')}</div>
    </div>`;
  bindProvider(el, p);
  if (S.focusKey) { $('.kform input', el)?.focus(); S.focusKey = false; }
}
function discHtml(d) {
  if (d.loading) return '<div class="disc"><span class="count">正在向 Provider 查询…</span></div>';
  if (d.error) return `<div class="disc"><div class="err">${esc(d.error)}</div></div>`;
  const fresh = d.items.filter(r => !r.added);
  return `<div class="disc"><div class="disc-h"><b>Provider 现在提供 ${d.items.length} 个 TTS 模型</b><span class="count">${fresh.length ? `其中 ${fresh.length} 个不在清单里` : '都已在清单里'}</span><span class="sp"></span><button class="btn ghost sm" type="button" data-dclose>收起</button></div>
    ${d.items.map(r => `<div class="disc-r"><code>${esc(r.remote)}</code><span class="count">${esc(r.name && r.name !== r.remote ? r.name : '')}${r.description ? ' · ' + esc(r.description) : ''}</span><span class="sp"></span>
      ${r.added ? '<span class="count">已在清单</span>' : `<button class="btn sm" type="button" data-dadd="${esc(r.remote)}" data-dname="${esc(r.name || '')}">添加</button>`}</div>`).join('')}</div>`;
}
function keyField(p, c, opt) {
  return `<div class="kf">
    <div class="lbl"><span>${esc(c.label)}</span><span class="key">${esc(c.env)}</span></div>
    ${c.configured ? `<div class="kset"><span class="pill loaded">已配置</span><span class="count">来自${c.source === 'env' ? '环境变量' : '配置文件'}${c.last4 ? ' · …' + esc(c.last4) : ''}</span>${c.source === 'file' ? `<button class="btn ghost sm" type="button" data-delkey="${esc(c.env)}">删除</button>` : ''}</div>` : ''}
    ${c.source === 'env' ? '' : `<form data-env="${esc(c.env)}" class="kform"><input class="in mono" type="password" autocomplete="off" spellcheck="false" placeholder="${c.configured ? '粘贴新值以替换' : opt ? '可选' : '粘贴 Key'}" aria-label="${esc(c.env)}"><button class="btn ${opt || c.configured ? '' : 'primary'}" type="submit">保存</button></form>`}</div>`;
}
async function afterModels() { await Promise.all([refreshModels(), api('/api/providers').then(p => S.providers = p)]); await refreshVoices(); }
function bindProvider(el, p) {
  const again = () => pageModels($('#main'));
  $$('[data-copy]', el).forEach(b => b.onclick = () => copy(b.dataset.copy, '已复制命令'));
  $$('form[data-env]', el).forEach(f => f.onsubmit = async e => {
    e.preventDefault(); const inp = $('input', f), v = inp.value.trim(); if (!v) return toast('先粘贴 Key');
    try { await api('/api/keys', { env: f.dataset.env, value: v }); inp.value = ''; toast(`已保存 ${f.dataset.env}`); await afterModels(); again(); }
    catch (err) { toast(err.message, 5000); }
  });
  $$('[data-delkey]', el).forEach(b => b.onclick = async () => { await api('/api/keys/delete', { env: b.dataset.delkey }); toast('已从配置文件删除'); await afterModels(); again(); });
  const f = $('#dFetch', el); if (f) f.onclick = async () => {
    S.disc = { pid: p.id, loading: true }; renderProvider(el);
    try { S.disc = { pid: p.id, items: await api('/api/providers/discover', { provider: p.id }) }; } catch (e) { S.disc = { pid: p.id, error: e.message }; }
    renderProvider(el);
  };
  $('[data-dclose]', el)?.addEventListener('click', () => { S.disc = null; renderProvider(el); });
  const add = async (remote, name) => {
    try { const r = await api('/api/models/add', { provider: p.id, remote, name: name || undefined }); toast(`已添加 ${r.model}`); }
    catch (e) { return toast(e.message, 5000); }
    if (S.disc?.pid === p.id && S.disc.items) S.disc.items.forEach(x => { if (x.remote === remote) x.added = true; });
    await afterModels(); again();
  };
  $$('[data-dadd]', el).forEach(b => b.onclick = () => { b.disabled = true; add(b.dataset.dadd, b.dataset.dname); });
  const t = $('#dAddT', el); if (t) t.onclick = () => { S.addOpen = S.addOpen === p.id ? null : p.id; renderProvider(el); if (S.addOpen) $('#dAdd input', el).focus(); };
  const af = $('#dAdd', el); if (af) af.onsubmit = e => { e.preventDefault(); const v = $('input', af).value.trim(); if (v) { S.addOpen = null; add(v); } };
  $$('[data-en]', el).forEach(i => i.onchange = async () => {
    try { await api('/api/models/enable', { model: i.dataset.en, enabled: i.checked }); } catch (e) { i.checked = !i.checked; return toast(e.message, 5000); }
    await afterModels(); again();
  });
  $$('[data-rm]', el).forEach(b => b.onclick = async () => { await api('/api/models/remove', { model: b.dataset.rm }).catch(e => toast(e.message, 5000)); toast('已从清单删除'); await afterModels(); again(); });
  $$('[data-pull]', el).forEach(b => b.onclick = async () => { await api('/api/models/pull', { model: b.dataset.pull }); await refreshModels(); again(); });
  $$('[data-load]', el).forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = '加载中…'; try { const r = await api('/api/models/load', { model: b.dataset.load }); toast(`已加载，用时 ${r.seconds}s`); } catch (e) { toast(e.message, 5000); } await refreshModels(); refreshStatus(); again(); });
  $$('[data-unload]', el).forEach(b => b.onclick = async () => { await api('/api/models/unload', { model: b.dataset.unload }); await refreshModels(); refreshStatus(); again(); });
  $$('[data-trym]', el).forEach(a => a.onclick = () => { ensureSlots(); Object.assign(slot(), newSlot({ model: a.dataset.trym })); saveSlots(); });
  $$('[data-keyfocus]', el).forEach(a => a.onclick = e => { e.preventDefault(); const i = $('.kform input', el); i?.scrollIntoView({ block: 'center' }); i?.focus(); });
}
function estimateLocal(r) { // 与服务端 hub.estimate 同一口径，只给按字符 / 字节计费的模型估算
  const m = M(r.model), p = m?.price; if (!p || m.provider === 'local' || p.amount == null) return null;
  const t = r.input || '', n = p.unit === 'byte' ? new TextEncoder().encode(t).length : p.unit === 'cjk2' ? [...t].reduce((a, c) => a + (/[\u3400-\u9fff]/.test(c) ? 2 : 1), 0) : [...t].length;
  const v = p.amount * n / p.per; return `${p.currency === 'CNY' ? '¥' : '$'}${v < 0.0001 ? v.toExponential(1) : v.toFixed(4)}`;
}
function priceText(m) {
  const p = m.price; if (!p) return null;
  if (p.text) return esc(p.text);
  const sym = p.currency === 'CNY' ? '¥' : '$', per = { 1000: '千', 10000: '万', 1000000: '百万' }[p.per] || p.per;
  return `${sym}${p.amount} / ${per}${{ char: '字符', byte: 'UTF-8 字节', cjk2: '字符（汉字按 2）' }[p.unit] || ''}`;
}
function modelCard(m) {
  const c = m.caps, cloud = m.provider !== 'local';
  const facts = cloud ? [priceText(m) || (m.custom ? '价格见 Provider 官网' : null), m.voice_count ? `${m.voice_count} 个音色` : null, `<code>${esc(m.remote || '')}</code>`].filter(Boolean) :
    [`<b>${m.params_b >= 1 ? m.params_b + 'B' : Math.round(m.params_b * 1000) + 'M'}</b> 参数`, esc(m.quant), `${m.size_gb} GB`, esc(m.license), m.voice_count ? `${m.voice_count} 个音色` : null].filter(Boolean);
  const cmd = !m.enabled ? `vox models on ${m.id}` : cloud ? (m.status === 'needs_key' ? `vox keys set ${m.key_env}` : `vox say "你好" -m ${m.id}`) : m.status === 'not_downloaded' ? `vox pull ${m.alias}` : m.status === 'loaded' ? `vox unload ${m.alias}` : `vox load ${m.alias}`;
  const rm = m.custom ? `<button class="btn ghost sm" type="button" data-rm="${esc(m.id)}">删除</button>` : '';
  const acts = !m.enabled ? rm :
    m.status === 'needs_key' ? `<a class="btn" href="#" data-keyfocus>先填 Key</a>${rm}` :
    m.status === 'not_downloaded' ? (m.alias === 'kokoro' ? '<span class="count">首次合成时自动下载</span>' : `<button class="btn primary" type="button" data-pull="${m.id}">下载 ${m.size_gb} GB</button>`) :
    m.status === 'downloading' ? `<span class="count" data-prog="${m.id}">下载中…</span><div class="bar"><i data-bar="${m.id}"></i></div>` :
    `<div style="display:flex;gap:6px"><a class="btn primary" href="#/playground" data-trym="${m.id}">去试音</a>${m.status === 'loaded' ? `<button class="btn" type="button" data-unload="${m.id}">卸载</button>` : cloud ? rm : `<button class="btn" type="button" data-load="${m.id}">预加载</button>`}</div>`;
  return `<article class="mc ${cloud ? 'cloud' : ''} ${m.enabled ? '' : 'off'}" style="--m:${hue(m.id)}">
    <div><h3><label class="sw" title="${m.enabled ? '已启用：出现在音色库和试音台' : '已停用：不出现在音色库和试音台'}"><input type="checkbox" data-en="${esc(m.id)}" ${m.enabled ? 'checked' : ''} aria-label="启用 ${esc(m.name)}"><i></i></label>
      ${esc(m.name)} <span class="pill ${m.status}">${!m.enabled ? '已停用' : cloud && m.status === 'ready' ? '可用' : STATUS[m.status]}</span>${m.custom ? '<span class="tag">自行添加</span>' : ''} <code>${esc(m.id)}</code></h3>
      <p>${esc(m.about)}</p>
      <div class="facts">${facts.map(f => `<span>${f}</span>`).join('')}</div>
      <div class="cap" style="margin-top:8px">${[['voices', '预置音色'], ['instructions', m.instr_enum ? '情绪枚举' : '情绪指令'], ['design', '声音设计'], ['seed', '可复现'], ['native_speed', '原生语速']].map(([k, t]) => `<span class="${c[k] ? 'y' : 'n'}">${t}</span>`).join('')}</div>
      ${m.languages?.length || m.homepage ? `<div class="facts">${m.languages?.length ? `<span>语言：${esc(m.languages.join('、'))}</span>` : ''}${m.homepage ? `<a href="${esc(m.homepage)}" target="_blank" rel="noopener">模型主页 ↗</a>` : ''}</div>` : ''}</div>
    <div class="mc-acts">${acts}<button class="cli" type="button" data-copy="${esc(cmd)}">${esc(cmd)}</button></div></article>`;
}
function pollPull(main) {
  clearTimeout(S._poll);
  S._poll = setTimeout(async () => {
    const ids = S.models.filter(m => m.status === 'downloading').map(m => m.id); if (!ids.length || S.route !== 'models') return;
    for (const id of ids) {
      const st = await api('/api/models/pull?model=' + encodeURIComponent(id)).catch(() => null); if (!st) continue;
      const pct = st.total ? Math.min(100, st.done / st.total * 100) : 0;
      const bar = $(`[data-bar="${CSS.escape(id)}"]`), lab = $(`[data-prog="${CSS.escape(id)}"]`);
      if (bar) bar.style.transform = `scaleX(${pct / 100})`; if (lab) lab.textContent = `下载中 ${(st.done / 1e9).toFixed(2)} / ${(st.total / 1e9).toFixed(2)} GB`;
      if (st.state === 'done' || st.state === 'error') { if (st.state === 'error') toast(`下载失败：${st.error}`, 6000); else toast('下载完成，已校验'); await refreshModels(); await refreshVoices(); return pageModels(main); }
    }
    pollPull(main);
  }, 1500);
}

/* ============ API ============ */
function pageApi(main) {
  const ready = S.models.filter(usable), m = M(S.apiModel) && usable(M(S.apiModel)) ? M(S.apiModel) : ready[0] || S.models[0];
  const vs = S.voices.filter(v => v.model === m.id && v.kind === 'preset');
  const r = { model: m.id, input: '你好，这是来自 vox 的声音。', ...(m.caps.voices ? { voice: vs[0]?.voice || m.default_voice } : {}), ...(m.caps.design ? { instructions: S.cat.design[1] } : {}) };
  const js = `const res = await fetch("${ORIGIN}/v1/audio/speech", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${JSON.stringify({ ...r, response_format: 'mp3' })}),\n});\nconst audio = new Audio(URL.createObjectURL(await res.blob()));\naudio.play();`;
  const code = { curl: cmdOf(r, 'curl'), python: cmdOf(r, 'python'), js, cli: cmdOf(r, 'cli') };
  const tabs = { curl: 'cURL', python: 'Python', js: 'JavaScript', cli: 'CLI' };
  const eps = [['POST', '/v1/audio/speech', 'OpenAI 兼容：返回音频。扩展参数 seed、lang、temperature…；响应头 X-Vox-Seed'], ['GET', '/v1/models', 'OpenAI 兼容：模型列表'],
    ['GET', '/api/models', '模型、能力与状态'], ['POST', '/api/models/pull · load · unload', '下载 / 预加载 / 卸载'], ['GET', '/api/voices', '音色库，可按 model、lang、gender、q 筛选'],
    ['POST', '/api/voices/sample', '生成或取音色样本'], ['POST', '/api/speech', '合成并返回 JSON（含实际种子、时长、音频地址）'], ['GET', '/api/history', '历史，与 CLI 共享'],
    ['POST', '/api/asr', '读音校对'], ['GET', '/llms.txt', '给 Agent 的接口说明']];
  main.innerHTML = `
    <div class="head"><div><h1>API</h1><p>OpenAI 兼容。任何支持 OpenAI 语音接口的客户端，把 base URL 换成下面这个，就能用本地模型。</p></div></div>
    <div class="card"><div class="lbl" style="margin-bottom:8px"><span>Base URL</span><span class="key">api_key 任意填写，本地服务不校验</span></div>
      <div class="base"><code class="mono">${ORIGIN}/v1</code><button class="btn sm" type="button" data-copy="${ORIGIN}/v1">复制</button><a class="btn ghost sm" href="/llms.txt" target="_blank">给 Agent 的说明 llms.txt ↗</a></div></div>
    <div class="twocol">
      <div class="card code-card"><div class="equiv-head"><div class="seg">${Object.entries(tabs).map(([k, t]) => `<button type="button" data-at="${k}" class="${S.apiTab === k ? 'on' : ''}">${t}</button>`).join('')}</div><span class="sp"></span>
        <select class="in" id="apiModel" style="width:auto">${ready.map(x => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.id)}</option>`).join('')}</select>
        <button class="btn ghost sm" type="button" id="apiCopy">复制</button></div><pre>${esc(code[S.apiTab])}</pre></div>
      <div class="card"><div class="lbl" style="margin-bottom:6px"><span>接口</span></div><table class="ep">${eps.map(e => `<tr><td>${e[0]}</td><td>${esc(e[1])}</td><td>${esc(e[2])}</td></tr>`).join('')}</table></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="lbl" style="margin-bottom:6px"><span>统一的参数名</span></div>
      <table class="ep"><tr><td>CLI</td><td>-m · -v · -i · -s · --seed</td><td rowspan="3" style="color:var(--text-2)">三个入口用同一套名字：模型 <code>model</code>、音色 <code>voice</code>（也可写引用如 <code>qwen3:serena</code>、<code>my:&lt;id&gt;</code>）、情绪 / 声音描述 <code>instructions</code>、语速 <code>speed</code>、种子 <code>seed</code>。</td></tr>
      <tr><td>HTTP</td><td>model · voice · instructions · speed · seed</td></tr><tr><td>WebUI</td><td>模型 · 音色 · 情绪 · 语速 · 种子</td></tr></table></div>`;
  $$('[data-copy]', main).forEach(b => b.onclick = () => copy(b.dataset.copy));
  $$('[data-at]', main).forEach(b => b.onclick = () => { S.apiTab = b.dataset.at; pageApi(main); });
  $('#apiModel', main).onchange = e => { S.apiModel = e.target.value; pageApi(main); };
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
