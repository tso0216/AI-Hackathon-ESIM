// 趣分享 demo 前端（原生 JS，無框架）
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const short = (name) => name.replace('日本 ', '');

const S = {
  boot: null, state: null, nowLabel: '',
  screen: 'trip', day: 1, spotId: 'kiyomizu',
  tripRec: null, rec: null, selPlan: 'jp-2gb', selDays: 5,
  supportHistory: [], supportInit: false, shareSpot: null,
};

const SHARE_PROMPT = { usj_nintendo: '現在排隊大概多久？', arashiyama: '現在竹林人多嗎？' };
const WAVE = [10, 18, 26, 16, 30, 22, 34, 20, 28, 14, 24, 18, 30, 12, 20, 26, 16, 10];

// ---------------- API ----------------
async function api(path, body) {
  const init = body instanceof FormData ? { method: 'POST', body }
    : body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, init);
  const data = await r.json();
  if (data.now_label) S.nowLabel = data.now_label;
  if (data.state) { S.state = data.state; renderSide(); }
  return data;
}

// ---------------- 啟動 ----------------
async function boot() {
  const d = await api('/api/bootstrap');
  S.boot = d;
  buildStatic();
  fitPhone();
  window.addEventListener('resize', fitPhone);
  await goScene(d.state.scene);
}

function buildStatic() {
  $('#scene-list').innerHTML = S.boot.scenes.map((s) => `
    <button class="scene" data-scene="${s.id}">${esc(s.title)}</button>`).join('');
  $$('#scene-list .scene').forEach((b) => b.onclick = () => goScene(b.dataset.scene));
  $('#sd-ai').textContent = S.boot.ai.live ? 'OpenAI' : '模擬';

  $('#sw-returning').onchange = async (e) => { await api('/api/state', { returning: e.target.checked }); S.tripRec = null; S.rec = null; rerender(); };
  $('#sw-esim').onchange = async (e) => { await api('/api/state', { has_esim: e.target.checked }); rerender(); };
  $('#btn-reset-quota').onclick = async () => { await api('/api/state', { reset_quota: true }); rerender(); };
  $('#btn-reset').onclick = async () => {
    await api('/api/reset', {});
    Object.assign(S, { tripRec: null, rec: null, selPlan: 'jp-2gb', selDays: 5, supportHistory: [], supportInit: false, shareSpot: null });
    ['#support-log', '#live-log', '#spot-log'].forEach((s) => { $(s).innerHTML = ''; });
    await goScene('trip');
  };

  $$('[data-go]').forEach((el) => el.onclick = () => show(el.dataset.go));

  const t = S.boot.trip;
  $('#trip-title').textContent = t.title.replace(/遊$/, '');

  $('#btn-quiz').onclick = () => openQuiz();
  $('#btn-buy').onclick = buy;
  bindComposer('#support-form', sendSupport);

  $$('#spot-tabs button').forEach((b) => b.onclick = () => {
    $$('#spot-tabs button').forEach((x) => x.classList.toggle('on', x === b));
    $$('#spot-body .tab-pane').forEach((p) => p.classList.toggle('on', p.dataset.pane === b.dataset.tab));
    $('#spot-form').hidden = $('#spot-suggest').hidden = b.dataset.tab !== 'ask';
  });
  bindComposer('#spot-form', (q) => askQA(q, S.spotId, $('#spot-log')));

  bindComposer('#live-form', (q) => askQA(q, liveSpot(), $('#live-log')));

  $('#btn-mic').onclick = toggleRecord;
  $$('[data-sample]').forEach((b) => b.onclick = () => useSample(b.dataset.sample));
  $('#btn-rerecord').onclick = () => { $('#share-text').value = ''; $('#share-result').innerHTML = ''; setTimer(0); renderWave(0); };
  $('#btn-submit-share').onclick = submitShare;
  $('#sheet-wrap').onclick = (e) => { if (e.target.id === 'sheet-wrap') closeSheet(); };
  $('#modal-wrap').onclick = (e) => { if (e.target.id === 'modal-wrap') closeModal(); };
}

function bindComposer(sel, fn) {
  const form = $(sel);
  form.onsubmit = (e) => {
    e.preventDefault();
    const input = $('input', form);
    const v = input.value.trim();
    if (!v) return;
    input.value = '';
    fn(v);
  };
}

function fitPhone() {
  // 依視窗高度與寬度放大到最大（上限 1.4 倍）
  const w = $('#stage').clientWidth - 32;
  const s = Math.min(1.4, (window.innerHeight - 32) / 872, w / 418);
  $('#phone').style.setProperty('--s', s.toFixed(3));
  $('#stage').style.minHeight = `${Math.round(872 * s + 32)}px`;
}

// ---------------- 情境與畫面切換 ----------------
async function goScene(id) {
  const d = await api('/api/scene', { scene: id });
  const sc = d.scene;
  if (sc.spot) S.spotId = sc.spot;
  $('#live-log').innerHTML = '';
  if (id === 'share') {
    // 先停在旅途中畫面，模擬收到推播邀請
    show('live');
    setTimeout(() => showPush(`在${S.state.location_name.split('・').pop()}嗎？說 30 秒送 500MB 🎁`, () => show('share')), 700);
  } else {
    show(sc.screen);
  }
}

function show(screen) {
  S.screen = screen;
  hidePush();
  closeSheet();
  closeModal();
  $$('.screen').forEach((s) => s.classList.toggle('on', s.dataset.screen === screen));
  rerender();
}

function rerender() {
  ({ trip: renderTrip, store: renderStore, support: renderSupport, spot: renderSpot,
     live: renderLive, share: renderShare, me: renderMe })[S.screen]?.();
}

function renderSide() {
  const st = S.state;
  $$('#scene-list .scene').forEach((b) => b.classList.toggle('on', b.dataset.scene === st.scene));
  $('#sd-now').textContent = (S.nowLabel || st.now).replace(/^\d{4}\//, '');
  $('#sd-loc').textContent = st.location_name || '台灣';
  $('#sw-returning').checked = st.returning;
  $('#sw-esim').checked = st.has_esim;
  $('#sd-bound').textContent = st.app_bound ? '是' : '否';
  $('#sd-bonus').textContent = `${st.bonus_mb}MB`;
  $('#sd-quota').textContent = `${st.qa_left}/${st.qa_quota}`;
}

// ---------------- 行程（解法 1） ----------------
function renderTrip() {
  const t = S.boot.trip;
  $('#day-chips').innerHTML = t.days.map((d) => `<button class="pill ${d.day === S.day ? 'on' : ''}" data-day="${d.day}">Day ${d.day}</button>`).join('');
  $$('#day-chips .pill').forEach((b) => b.onclick = () => { S.day = +b.dataset.day; renderTrip(); });
  const day = t.days[S.day - 1];
  $('#day-items').innerHTML = day.items.map((i) => {
    const sp = S.boot.spots[i.spot_id];
    return `<div class="tl-item" data-spot="${i.spot_id}"><span class="tl-dot"></span><span class="tl-time">${i.time}</span><span class="tl-name">${esc(sp.name)}</span></div>`;
  }).join('');
  $$('#day-items .tl-item').forEach((el) => el.onclick = () => { S.spotId = el.dataset.spot; $('#spot-log').innerHTML = ''; show('spot'); });
  renderTripCard();
}

async function renderTripCard() {
  const box = $('#trip-ai-card');
  const st = S.state;
  const hd = (title) => `<div class="ai-hd"><span class="ai-badge">AI</span>${title}</div>`;
  if (st.has_esim) {
    box.innerHTML = `${hd('已購買的 eSIM')}<div class="ai-plan">${esc(short(st.esim.name))} × ${st.esim.days} 天</div>
      <div class="ai-sub">出發前在 Wi-Fi 下安裝</div>`;
    return;
  }
  if (!S.tripRec) {
    box.innerHTML = `${hd('這趟建議的 eSIM')}<div><span class="spinner"></span></div>`;
    S.tripRec = await api('/api/advisor/recommend', { answers: {} });
    if (S.screen !== 'trip') return;
  }
  const r = S.tripRec;
  box.innerHTML = `${hd('這趟建議的 eSIM')}
    <div class="ai-plan">${esc(short(r.plan.name)).replace('GB', 'GB ')}× ${r.plan.days} 天</div>
    <div class="ai-sub">${esc(r.reason)}</div>
    <button class="pill-btn" id="btn-trip-cart">一鍵加入購物車</button>`;
  $('#btn-trip-cart').onclick = () => { S.selPlan = r.plan.id; S.selDays = r.plan.days; S.rec = S.rec || r; show('store'); toast('已加入購物車'); };
}

// ---------------- 商店（解法 1） ----------------
function renderStore() {
  $('#store-days').innerHTML = [3, 5, 7].map((d) => `<button class="pill ${d === S.selDays ? 'on' : ''}" data-d="${d}">${d} 天</button>`).join('');
  $$('#store-days .pill').forEach((b) => b.onclick = () => { S.selDays = +b.dataset.d; renderStore(); });
  const recId = S.rec?.plan.id;
  $('#plan-list').innerHTML = S.boot.plans.map((p) => `
    <button class="plan ${p.id === S.selPlan ? 'on' : ''}" data-id="${p.id}">
      ${p.id === recId ? '<span class="tag">AI 推薦</span>' : ''}
      <span class="pn">${esc(short(p.name))}</span><span class="pp">NT$${p.prices[S.selDays]}</span>
    </button>`).join('');
  $$('#plan-list .plan').forEach((b) => b.onclick = () => { S.selPlan = b.dataset.id; renderStore(); });
  const plan = S.boot.plans.find((p) => p.id === S.selPlan);
  const owned = S.state.esim?.plan_id === S.selPlan;
  $('#btn-buy').textContent = owned ? '已購買' : `購買・NT$${plan.prices[S.selDays]}`;
  $('#btn-buy').disabled = owned;
  renderRec();
}

function renderRec() {
  const box = $('#rec-box');
  const r = S.rec;
  if (!r) { box.innerHTML = ''; return; }
  const max = Math.max(...r.contributions.map((c) => Math.abs(c.gb)), 0.1);
  box.innerHTML = `<div class="rec">
    <div><b class="teal">AI 推薦　${esc(short(r.plan.name))} × ${r.plan.days} 天</b></div>
    <div>${esc(r.reason)}</div>
    <details><summary class="link">每日 ${r.estimate_gb}GB 怎麼算？</summary>
      <div class="factors">${r.contributions.map((c) => `
        <div class="factor"><span>${esc(c.factor)}</span><span class="bar"><b class="${c.gb < 0 ? 'neg' : ''}" style="width:${Math.abs(c.gb) / max * 100}%"></b></span><span class="v">${c.gb > 0 ? '+' : ''}${c.gb}</span></div>`).join('')}
      </div></details>
  </div>`;
}

function openQuiz() {
  const quiz = S.boot.quiz;
  const answers = {};
  const step = (i) => {
    if (i >= quiz.length) { closeSheet(); runAdvisor(answers); return; }
    const q = quiz[i];
    openSheet(`<div class="handle"></div><div class="sheet-hd"><b>AI 幫我選</b><span class="muted">${i + 1} / ${quiz.length}</span></div><div class="q">${esc(q.q)}</div>
      ${q.options.map(([v, label]) => `<button class="opt" data-v="${v}">${esc(label)}</button>`).join('')}`);
    $$('#sheet .opt').forEach((b) => b.onclick = () => { answers[q.key] = b.dataset.v; step(i + 1); });
  };
  step(0);
}

async function runAdvisor(answers) {
  $('#rec-box').innerHTML = '<div class="rec"><span><span class="spinner"></span> AI 估算中</span></div>';
  const r = await api('/api/advisor/recommend', { answers });
  S.rec = r; S.selPlan = r.plan.id; S.selDays = r.plan.days;
  if (S.screen === 'store') renderStore();
}

async function buy() {
  await api('/api/checkout', { plan_id: S.selPlan });
  toast('購買成功');
  renderStore();
}

// ---------------- 客服（解法 1） ----------------
function renderSupport() {
  if (!S.supportInit) {
    S.supportInit = true;
    $('#support-log').innerHTML = '<div class="msg ai">你好！安裝、相容、方案問題都可以問我。</div>';
  }
  const qs = ['iPhone 12 能用嗎？', '怎麼安裝？', '可以開熱點嗎？', '用完會怎樣？', '可以退款嗎？', '推薦餐廳？'];
  $('#support-chips').innerHTML = qs.map((q) => `<button class="pill line">${esc(q)}</button>`).join('');
  $$('#support-chips .pill').forEach((b) => b.onclick = () => sendSupport(b.textContent));
}

async function sendSupport(text) {
  const log = $('#support-log');
  addMsg(log, 'me', esc(text));
  const typing = addMsg(log, 'ai typing', '<span class="spinner"></span>');
  const r = await api('/api/support/chat', { message: text, history: S.supportHistory });
  typing.remove();
  S.supportHistory.push({ role: 'user', content: text }, { role: 'assistant', content: r.answer });
  addMsg(log, 'ai', esc(r.answer));
  if (r.handoff) {
    const b = document.createElement('button');
    b.className = 'handoff'; b.textContent = '轉真人客服';
    b.onclick = () => { b.remove(); addMsg(log, 'sys', '已轉接真人客服'); };
    log.appendChild(b); scrollEnd(log);
  }
}

// ---------------- 問經驗（解法 2） ----------------
function renderSpot() {
  const sp = S.boot.spots[S.spotId];
  $('#spot-name').textContent = sp.name;
  $('#spot-area').textContent = sp.area;
  $('[data-pane="intro"]').innerHTML = `<div class="review">${esc(sp.intro)}</div>`;
  const rv = S.boot.reviews[S.spotId] || [];
  const latest = rv.map((r) => r.date).sort().pop();
  $('[data-pane="reviews"]').innerHTML = `<div class="stale">${latest ? `最新評論：${latest.slice(0, 7).replace('-', '/')}` : '還沒有評論'}</div>`
    + rv.map((r) => `<div class="review"><div class="rv-hd"><span>${'★'.repeat(r.stars)}</span><span>${r.date}</span></div>${esc(r.text)}</div>`).join('');

  const log = $('#spot-log');
  const month = +S.boot.trip.start.slice(5, 7);
  const chips = [`${month} 月平日早上人多嗎？`, ...sp.faq];
  $('#spot-chips').innerHTML = chips.map((q) => `<button class="pill line">${esc(q)}</button>`).join('');
  $$('#spot-chips .pill').forEach((b) => b.onclick = () => askQA(b.textContent, S.spotId, log));
}

async function askQA(question, spotId, log) {
  addMsg(log, 'me', esc(question));
  const typing = addMsg(log, 'ai typing', '<span class="spinner"></span>');
  const r = await api('/api/qa/ask', { question, spot_id: spotId });
  typing.remove();
  if (r.quota_exceeded) {
    openQuotaModal();
  } else {
    const src = r.sources?.length ? `<details class="src"><summary>${esc(r.meta)}</summary><ul>${r.sources.map((s) =>
      `<li>${esc(s.summary)}・${esc(s.ago)}</li>`).join('')}</ul></details>` : '';
    addMsg(log, 'ai', `${esc(r.answer)}${src}`);
  }
  if (S.screen === 'live') renderLiveHeader();
}

// ---------------- 旅途中（解法 2） ----------------
function liveSpot() { return S.state.location || 'arashiyama'; }

function renderLiveHeader() {
  const st = S.state;
  const pill = $('#live-quota');
  pill.textContent = st.has_esim ? `eSIM 額度 ${st.qa_left}` : `免費 ${st.qa_left} 次`;
}

async function renderLive(highlightId) {
  const id = liveSpot();
  const sp = S.boot.spots[id];
  const name = sp.name.split('・').pop();
  $('#live-loc').textContent = `● 目前位置：${name}`;
  renderLiveHeader();
  const chips = [`現在${name}人多嗎？`, ...sp.faq];
  if (id === 'arashiyama') chips.unshift('下雨還值得去嗎？');
  $('#live-chips').innerHTML = chips.map((q) => `<button class="pill line">${esc(q)}</button>`).join('');
  $$('#live-chips .pill').forEach((b) => b.onclick = () => askQA(b.textContent, id, $('#live-log')));

  const box = $('#live-reports');
  const d = await api(`/api/spots/${id}/reports`);
  box.innerHTML = '<div class="rp-title">最新旅人回報</div>'
    + (d.reports.length ? d.reports.slice(0, 3).map((r) => `<div class="rp ${r.id === highlightId ? 'new' : ''}"><span>${esc(r.summary)}</span><span>${esc(r.ago)}</span></div>`).join('')
      : '<div class="muted small">今天還沒有回報</div>');
}

function openQuotaModal() {
  openModal(`<div class="esim-ic">eSIM</div><h3>免費查詢已用完</h3>
    <p>eSIM 用戶享專屬查詢額度，旅途中隨時問</p>
    <button class="pill-btn" id="q-buy">購買 eSIM 解鎖更多查詢</button>
    <button class="pill-btn ghost" id="q-later">稍後再說</button>`);
  $('#q-buy').onclick = () => { closeModal(); show('store'); };
  $('#q-later').onclick = closeModal;
}

// ---------------- 分享（解法 3） ----------------
let rec = null;

function renderShare() {
  const id = S.state.location || 'usj_nintendo';
  if (S.shareSpot !== id) {
    S.shareSpot = id;
    $('#share-text').value = '';
    $('#share-result').innerHTML = '';
    setTimer(0);
  }
  $('#share-loc').textContent = `● ${S.boot.spots[id].name}`;
  $('#share-prompt').textContent = SHARE_PROMPT[id] || '現在現場狀況如何？';
  if (!$('#wave').children.length) renderWave(0);
}

function setTimer(sec) { $('#share-timer').textContent = `0:${String(sec).padStart(2, '0')} / 0:30`; renderWave(sec); }

function renderWave(sec, live = false) {
  const n = Math.round(WAVE.length * Math.min(sec, 30) / 30);
  $('#wave').innerHTML = WAVE.map((h, i) => `<i class="${i < n || live ? '' : 'off'}" style="height:${h}px;animation-delay:${i * 60}ms"></i>`).join('');
  $('#wave').classList.toggle('live', live);
}

async function toggleRecord() {
  const btn = $('#btn-mic');
  if (rec) { rec.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('無法錄音，請用範例'); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { toast('無法使用麥克風'); return; }
  const chunks = [];
  rec = new MediaRecorder(stream);
  let sec = 0;
  setTimer(0);
  renderWave(0, true);
  const timer = setInterval(() => { sec += 1; $('#share-timer').textContent = `0:${String(Math.min(sec, 30)).padStart(2, '0')} / 0:30`; if (sec >= 30) rec?.stop(); }, 1000);
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.onstop = async () => {
    clearInterval(timer);
    stream.getTracks().forEach((t) => t.stop());
    rec = null;
    btn.classList.remove('rec'); btn.classList.add('busy');
    setTimer(Math.min(sec, 30));
    const fd = new FormData();
    fd.append('audio', new Blob(chunks, { type: 'audio/webm' }), 'share.webm');
    fd.append('spot_id', S.shareSpot);
    $('#share-text').value = '轉文字中…';
    const r = await api('/api/share/transcribe', fd);
    btn.classList.remove('busy');
    $('#share-text').value = r.transcript;
  };
  rec.start();
  btn.classList.add('rec');
}

async function useSample(kind) {
  const fd = new FormData();
  fd.append('spot_id', S.shareSpot);
  fd.append('sample', kind);
  const r = await api('/api/share/transcribe', fd);
  $('#share-text').value = r.transcript;
  setTimer(kind === 'good' ? 18 : 5);
  $('#share-result').innerHTML = '';
}

async function submitShare() {
  const text = $('#share-text').value.trim();
  if (!text) { toast('請先錄音或用範例'); return; }
  const box = $('#share-result');
  box.innerHTML = '<div class="result"><span class="spinner"></span></div>';
  const r = await api('/api/share/submit', { transcript: text, spot_id: S.shareSpot });
  const s = r.structured;
  const noEsim = r.checks.some((c) => c.name === 'eSIM 在場' && !c.passed);
  box.innerHTML = `<div class="result ${r.passed ? 'ok' : 'ng'}">
    <div class="r-hd">${r.passed ? (r.reward_mb ? `✓ 審核通過，流量 +${r.reward_mb}MB` : '✓ 審核通過') : '✗ 未通過審核'}</div>
    <div class="struct"><span>類型</span><b>${esc(s.category)}${s.wait_minutes ? `・${s.wait_minutes} 分` : ''}</b><span>摘要</span><b>${esc(s.summary)}</b></div>
    <div class="checks">${r.checks.map((c) => `<span class="ck ${c.passed ? 'y' : 'n'}" title="${esc(c.detail)}">${c.passed ? '✓' : '✗'} ${esc(c.name)}</span>`).join('')}</div>
    ${r.passed ? '' : `<div class="muted small">${esc(r.checks.filter((c) => !c.passed).map((c) => c.detail).join('、'))}</div>`}
    ${r.passed ? '<button class="pill-btn" id="r-go">查看最新旅人回報</button>' : noEsim ? '<button class="pill-btn" id="r-buy">購買 eSIM</button>' : ''}
  </div>`;
  if (r.passed) {
    $('#r-go').onclick = () => { show('live'); renderLive(r.experience.id); };
    if (r.reward_mb) toast(`🎁 +${r.reward_mb}MB`);
  }
  if (noEsim) $('#r-buy').onclick = () => show('store');
  scrollEnd(box.closest('.body'));
}

// ---------------- 我的 ----------------
function renderMe() {
  const st = S.state;
  const e = st.esim;
  const totalMb = e ? (e.unlimited ? 10240 : e.daily_gb * 1024) : 0;
  const cards = st.cards;
  $('#me-body').innerHTML = `
    <div class="card row gap"><div class="ava">🧳</div><div class="grow"><b>去趣旅人</b></div>
      <span class="${st.app_bound ? 'tag-ok' : 'tag-no'}">${st.app_bound ? '已綁定 App' : '未綁定'}</span></div>

    <div class="card"><div class="card-title">eSIM</div>
      ${e ? `<div>${esc(short(e.name))} × ${e.days} 天</div>
        <div class="data-meter"><b style="flex:${totalMb}"></b><i style="flex:${st.bonus_mb}"></i></div>
        ${st.bonus_mb ? `<div class="small" style="color:var(--ok)">加碼 +${st.bonus_mb}MB</div>` : ''}`
        : '<button class="pill-btn" data-go2="store">購買 eSIM</button>'}
    </div>

    ${cards.length ? `<div class="exp-card">
      <div class="card-title">${esc(S.boot.trip.title)}經驗卡</div>
      <div class="stat"><div><b>${cards.length}</b>分享</div><div><b>${cards.length * 37}</b>人看過</div><div><b>+${st.bonus_mb}MB</b>流量</div></div>
      ${cards.map((c) => `<div class="ec-item"><small>${esc(c.spot_name)}</small>${esc(c.summary)}</div>`).join('')}
    </div>` : '<div class="card muted small">分享經驗後生成經驗卡</div>'}

    ${e ? `<div class="card row gap"><div class="grow"><b>下次去日本</b><div class="muted small">${esc(short(e.name))}・回購 9 折</div></div>
      <button class="pill line" data-go2="store">再買</button></div>` : ''}`;
  $$('#me-body [data-go2]').forEach((b) => b.onclick = () => show(b.dataset.go2));
}

// ---------------- 共用 UI ----------------
function addMsg(log, cls, html) {
  const el = document.createElement('div');
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  log.appendChild(el);
  scrollEnd(log);
  return el;
}

function scrollEnd(el) {
  const sc = el.closest('.body') || el;
  requestAnimationFrame(() => { sc.scrollTop = sc.scrollHeight; });
}

function openSheet(html) { $('#sheet').innerHTML = html; $('#sheet-wrap').classList.add('on'); }
function closeSheet() { $('#sheet-wrap').classList.remove('on'); }
function openModal(html) { $('#modal').innerHTML = html; $('#modal-wrap').classList.add('on'); }
function closeModal() { $('#modal-wrap').classList.remove('on'); }

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), 2000);
}

let pushTimer;
function showPush(msg, onClick) {
  $('#push-msg').textContent = msg;
  const p = $('#push');
  p.classList.add('on');
  p.onclick = () => { hidePush(); onClick(); };
  clearTimeout(pushTimer); pushTimer = setTimeout(hidePush, 8000);
}
function hidePush() { $('#push').classList.remove('on'); }

boot();
