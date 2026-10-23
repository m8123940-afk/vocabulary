// Telegram Mini App: интерфейс тренировки. Логика и данные — на сервере (miniapp/server.py).
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const params = new URLSearchParams(location.search);
const AUTH = params.get("dev") ? "dev:" + params.get("dev") : "tma " + (tg ? tg.initData : "");
const app = document.getElementById("app");

async function api(method, path, body) {
  const res = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: AUTH },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ("Ошибка " + res.status));
  return data;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), 3200);
}
function fail(err) { toast(err.message || String(err)); }
function setView(html) { app.innerHTML = html; }
function go(name) { location.hash = name; }
const bar = (done, total) => `<div class="bar"><div style="width:${total ? Math.round(100 * done / total) : 0}%"></div></div>`;

// ---------- голос ----------
function speak(text, rate = 1) {
  if (!("speechSynthesis" in window)) return toast("Озвучка недоступна в этом браузере");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US"; u.rate = rate;
  speechSynthesis.speak(u);
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function listen() {
  return new Promise((resolve, reject) => {
    if (!SR) return reject(new Error("Голосовой ввод недоступен здесь — ответьте текстом"));
    const r = new SR();
    r.lang = "ru-RU"; r.maxAlternatives = 5; r.interimResults = false;
    r.onresult = (e) => resolve([...e.results[0]].map((a) => a.transcript));
    r.onerror = () => reject(new Error("Речь не распознана — повторите, штрафа нет"));
    r.onnomatch = () => reject(new Error("Речь не распознана — повторите, штрафа нет"));
    r.start();
  });
}

// ---------- главная ----------
const TILES = [
  ["train", "📚", "Тренировка"], ["words", "📖", "Мои слова"], ["stats", "📊", "Статистика"],
  ["points", "⭐", "Мои баллы"], ["settings", "⚙️", "Настройки"], ["source", "🌐", "Источник слов"],
];
function viewHome() {
  setView(`<h2>Что будем делать?</h2><div class="grid">` +
    TILES.map(([id, ico, name]) => `<a class="tile" href="#${id}"><span class="ico">${ico}</span>${name}</a>`).join("") +
    `</div>`);
}

// ---------- тренировка ----------
async function viewTrain() {
  const st = await api("GET", "/train/state");
  if (st.active) return showQuestion(st);
  const units = await api("GET", "/train/units");
  if (!units.length) {
    return setView(`<h2>Тренировка</h2><div class="card"><p>Слов пока нет.</p><a class="btn" href="#source">Загрузить словарь</a></div>`);
  }
  setView(`<h2>Выберите Unit и Part</h2>` + units.map((u) => `
    <div class="card"><h3>Unit ${esc(u.unit)} <span class="pill">${u.count} сл.</span></h3>
      <button class="block" onclick="startTrain('${esc(u.unit)}','*')">📦 Все Part</button>
      ${u.parts.map((p) => `<button class="block secondary" onclick="startTrain('${esc(u.unit)}','${esc(p.part)}')">
        ${p.part ? "Part " + esc(p.part) : "Без Part"} · ${p.count} сл.</button>`).join("")}
    </div>`).join(""));
}
window.startTrain = async (unit, part) => {
  try { showQuestion(await api("POST", "/train/start", { unit, part })); } catch (e) { fail(e); }
};
window.againTrain = async () => { try { showQuestion(await api("POST", "/train/again")); } catch (e) { fail(e); } };
window.retryFrom = async (sid) => { try { showQuestion(await api("POST", `/train/retry/${sid}`)); } catch (e) { fail(e); } };

function showQuestion(st, feedback) {
  const shown = st.index + (feedback ? 0 : 1);
  setView(`
    <h2>${st.mode === "retry" ? "🔁 Повтор ошибок" : "Тренировка"} · Unit ${esc(st.unit)} ${st.part === "*" ? "" : "Part " + esc(st.part)}</h2>
    ${bar(st.index, st.total)}
    <p class="muted">Слово ${Math.min(shown, st.total)} из ${st.total} · ❌ ошибок: ${st.errors}</p>
    <div class="card word-card">
      <button class="secondary" onclick="speak('${esc(st.word_en)}', ${(await_rate())})">🔊 Слушать слово</button>
      <p class="muted">Ответьте по-русски голосом или текстом</p>
      <button id="mic" class="mic" onclick="voiceAnswer()">🎤</button>
      <div class="row"><input id="txt" placeholder="Перевод текстом"><button class="auto" onclick="textAnswer()">Ответить</button></div>
      <button class="secondary block" onclick="skipWord()">⏭ Пропустить</button>
    </div>
    <div id="fb"></div>
    <button class="secondary block" onclick="finishTrain()">⏹ Завершить тренировку</button>`);
  if (feedback) document.getElementById("fb").innerHTML = feedback;
  else speak(st.word_en, 1);
}
let cachedRate = 1;
function await_rate() { return cachedRate; }
api("GET", "/settings").then((s) => (cachedRate = s.tts_rate)).catch(() => {});

window.voiceAnswer = async () => {
  const btn = document.getElementById("mic");
  btn.classList.add("rec");
  try { await sendAnswer({ said: "", alternatives: await listen() }); }
  catch (e) { fail(e); } finally { btn.classList.remove("rec"); }
};
window.textAnswer = () => {
  const v = document.getElementById("txt").value.trim();
  if (!v) return toast("Введите перевод");
  sendAnswer({ said: v, alternatives: [] });
};
async function sendAnswer(body) {
  try {
    const r = await api("POST", "/train/answer", body);
    const head = r.correct ? `<b>✅ Верно!</b>` : `<b>❌ Неверно.</b>`;
    const fb = `<div class="feedback ${r.correct ? "ok" : "bad"}">${head}<br>
      Вы сказали: «${esc(r.said)}»<br>🇬🇧 <b>${esc(r.en)}</b> — ${esc(r.ru)}<br>
      <span class="muted">Прогресс ${r.done}/${r.total} · ошибок: ${r.errors}</span></div>
      <button class="block" onclick="nextStep()">${r.done >= r.total ? "🏁 Итоги" : "Дальше →"}</button>`;
    markAnswered(fb);
  } catch (e) { fail(e); }
}
window.skipWord = async () => {
  try {
    const r = await api("POST", "/train/skip");
    markAnswered(`<div class="feedback bad">⏭ Пропущено. Перевод: <b>${esc(r.ru)}</b> (${esc(r.en)})</div>
      <button class="block" onclick="nextStep()">${r.done >= r.total ? "🏁 Итоги" : "Дальше →"}</button>`);
  } catch (e) { fail(e); }
};
function markAnswered(html) {
  document.getElementById("fb").innerHTML = html;
  document.querySelectorAll(".word-card button").forEach((b) => (b.disabled = true));
}
window.nextStep = async () => {
  try {
    const st = await api("GET", "/train/state");
    if (!st.active || st.word_en === null) return finishTrain();
    showQuestion(st);
  } catch (e) { fail(e); }
};
window.finishTrain = async () => {
  try {
    const rep = await api("POST", "/train/finish");
    const s = await api("GET", "/settings");
    const pts = rep.mode === "retry" ? "баллы за повтор не начисляются" : `баллы за тренировку: <b>${rep.points >= 0 ? "+" : ""}${rep.points}</b>`;
    setView(`<h2>🏁 Тренировка завершена</h2>
      <div class="card">
        <div class="stat"><span>Всего слов</span><b>${rep.total}</b></div>
        <div class="stat"><span>✅ Правильных</span><b>${rep.correct}</b></div>
        <div class="stat"><span>❌ Ошибок</span><b>${rep.errors}</b></div>
        <div class="stat"><span>⏭ Пропусков</span><b>${rep.skipped}</b></div>
        <div class="stat"><span>🎯 Точность</span><b>${rep.percent}%</b></div>
        <p>${pts}<br>🏆 Общий баланс: <b>${rep.balance}</b></p>
      </div>
      ${rep.wrong_ids.length ? `<button class="block" onclick="retryFrom(${rep.session_id})">🔁 Повторить ошибки (${rep.wrong_ids.length})</button>` : ""}
      <button class="block secondary" onclick="againTrain()">🔄 Пройти заново</button>
      <a class="btn block secondary" style="display:block;text-align:center" href="#home">🏠 Главное меню</a>
      ${s.retry_errors ? `<p class="muted">Совет: в настройках включён автоповтор ошибок — он запускается из раздела «Тренировка».</p>` : ""}`);
  } catch (e) { fail(e); }
};

// ---------- слова ----------
async function viewWords() {
  const words = await api("GET", "/words");
  setView(`<h2>Мои слова <span class="pill">${words.length}</span></h2>
    <div class="card"><h3>Добавить слово</h3>
      <input id="w-en" placeholder="English"><input id="w-ru" placeholder="Перевод">
      <button class="block" onclick="addWord()">➕ Добавить</button></div>
    <div class="card">${words.slice(0, 200).map((w) => `
      <div class="list-item"><div><b>${esc(w.en)}</b> — ${esc(w.ru)}
        <div class="muted">Unit ${esc(w.unit)}${w.part ? " · Part " + esc(w.part) : ""}</div></div>
        <div class="row auto"><button class="secondary" onclick="editWord(${w.id},'${esc(w.en)}','${esc(w.ru)}')">✏️</button>
        <button class="danger" onclick="delWord(${w.id})">🗑</button></div></div>`).join("") || `<p class="muted">Список пуст</p>`}
    </div>`);
}
window.addWord = async () => {
  const en = document.getElementById("w-en").value.trim(), ru = document.getElementById("w-ru").value.trim();
  try { await api("POST", "/words", { en, ru }); toast("Добавлено"); viewWords(); } catch (e) { fail(e); }
};
window.editWord = async (id, en, ru) => {
  const newEn = prompt("Английское слово", en); if (newEn === null) return;
  const newRu = prompt("Перевод", ru); if (newRu === null) return;
  try { await api("PUT", `/words/${id}`, { en: newEn, ru: newRu }); viewWords(); } catch (e) { fail(e); }
};
window.delWord = async (id) => {
  if (!confirm("Удалить слово?")) return;
  try { await api("DELETE", `/words/${id}`); viewWords(); } catch (e) { fail(e); }
};

// ---------- статистика и баллы ----------
async function viewStats() {
  const s = await api("GET", "/stats");
  const t = s.totals;
  setView(`<h2>📊 Статистика</h2>
    <div class="card">
      <div class="stat"><span>Всего слов</span><b>${t.total}</b></div>
      <div class="stat"><span>✅ Правильных</span><b>${t.correct}</b></div>
      <div class="stat"><span>❌ Ошибок</span><b>${t.errors}</b></div>
      <div class="stat"><span>⏭ Пропусков</span><b>${t.skipped}</b></div>
      <div class="stat"><span>🎯 Процент правильных</span><b>${s.percent}%</b></div>
      <div class="stat"><span>🏆 Баланс</span><b>${s.balance}</b></div>
    </div>
    <h3>По Unit и Part</h3>
    <div class="card">${s.by_unit_part.map((r) => `<div class="stat"><span>Unit ${esc(r.unit)} / Part ${esc(r.part || "—")}</span>
      <b>${r.total ? Math.round(100 * r.correct / r.total) : 0}% · ${r.total} сл.</b></div>`).join("") || `<p class="muted">Пока нет данных</p>`}</div>
    <h3>История</h3>
    <div class="card">${s.history.map((h) => `<div class="stat"><span>#${h.id} · Unit ${esc(h.unit)} ${esc(h.part)} ${h.mode === "retry" ? "(повтор)" : ""}</span>
      <b>${h.points >= 0 ? "+" : ""}${h.points}</b></div>`).join("") || `<p class="muted">Тренировок пока нет</p>`}</div>`);
}
async function viewPoints() {
  const p = await api("GET", "/points");
  setView(`<h2>⭐ Мои баллы</h2>
    <div class="card"><p style="font-size:28px;margin:4px 0"><b>${p.balance}</b></p><p class="muted">общий баланс</p></div>
    <h3>Последние тренировки</h3>
    <div class="card">${p.history.map((h) => `<div class="stat"><span>#${h.id}</span><b>${h.points >= 0 ? "+" : ""}${h.points}</b></div>`).join("") || `<p class="muted">Пока нет</p>`}</div>
    <a class="btn block secondary" style="display:block;text-align:center" href="#settings">📋 Таблица баллов</a>`);
}

// ---------- настройки и таблица баллов ----------
async function viewSettings() {
  const [s, rules] = await Promise.all([api("GET", "/settings"), api("GET", "/rules")]);
  setView(`<h2>⚙️ Настройки</h2>
    <div class="card">
      <h3>Тренировка</h3>
      <label class="muted">Слов за тренировку</label>
      <select id="s-words">${[5, 10, 15, 20, 30].map((n) => `<option ${n === s.words_per_session ? "selected" : ""}>${n}</option>`).join("")}</select>
      <label class="muted">Скорость озвучки</label>
      <select id="s-rate"><option value="0.7" ${s.tts_rate < 0.9 ? "selected" : ""}>Медленная</option><option value="1" ${s.tts_rate >= 0.9 ? "selected" : ""}>Обычная</option></select>
      <label><input type="checkbox" id="s-shuffle" ${s.shuffle ? "checked" : ""} style="width:auto"> Случайный порядок</label><br>
      <label><input type="checkbox" id="s-retry" ${s.retry_errors ? "checked" : ""} style="width:auto"> Повторять ошибки после тренировки</label>
      <button class="block" onclick="saveSettings()">Сохранить</button>
    </div>
    <div class="card">
      <h3>Таблица баллов</h3>
      ${rules.overlaps ? `<p class="muted">⚠️ Есть пересекающиеся диапазоны — применяется первое подходящее.</p>` : ""}
      ${rules.rules.map((r) => `<div class="list-item"><div>${ruleLabel(r)}</div>
        <div class="row auto"><button class="secondary" onclick="editRule(${r.id})">✏️</button>
        <button class="danger" onclick="delRule(${r.id})">🗑</button></div></div>`).join("")}
      <h3>Новое правило</h3>
      <div class="row"><input id="r-min" type="number" min="0" placeholder="от ошибок">
        <input id="r-max" type="number" min="0" placeholder="до (пусто = ∞)"></div>
      <select id="r-pts">${pointOptions(0)}</select>
      <button class="block" onclick="addRule()">➕ Добавить правило</button>
      <button class="block secondary" onclick="resetRules()">♻️ Восстановить стандартную таблицу</button>
    </div>`);
}
const ruleLabel = (r) => {
  const rng = r.max_errors === null ? `${r.min_errors}+` : r.min_errors === r.max_errors ? `${r.min_errors}` : `${r.min_errors}–${r.max_errors}`;
  return `<b>${rng}</b> ошибок → <b>${r.points >= 0 ? "+" : ""}${r.points}</b> баллов`;
};
const pointOptions = (sel) => [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5].map((v) => `<option value="${v}" ${v === sel ? "selected" : ""}>${v > 0 ? "+" + v : v}</option>`).join("");
window.saveSettings = async () => {
  try {
    await api("PUT", "/settings", {
      words_per_session: Number(document.getElementById("s-words").value),
      tts_rate: Number(document.getElementById("s-rate").value),
      shuffle: document.getElementById("s-shuffle").checked,
      retry_errors: document.getElementById("s-retry").checked,
    });
    toast("Сохранено"); viewSettings();
  } catch (e) { fail(e); }
};
function parseRule() {
  const min = Number(document.getElementById("r-min").value);
  const maxRaw = document.getElementById("r-max").value.trim();
  return { min_errors: min, max_errors: maxRaw === "" ? null : Number(maxRaw), points: Number(document.getElementById("r-pts").value) };
}
window.addRule = async () => {
  try { await api("POST", "/rules", parseRule()); toast("Правило добавлено"); viewSettings(); } catch (e) { fail(e); }
};
window.editRule = async (id) => {
  const { rules } = await api("GET", "/rules");
  const r = rules.find((x) => x.id === id);
  const min = prompt("От ошибок", r.min_errors); if (min === null) return;
  const max = prompt("До ошибок (пусто = ∞)", r.max_errors ?? ""); if (max === null) return;
  const pts = prompt("Баллы (от -5 до 5)", r.points); if (pts === null) return;
  try {
    await api("PUT", `/rules/${id}`, { min_errors: Number(min), max_errors: max.trim() === "" ? null : Number(max), points: Number(pts) });
    viewSettings();
  } catch (e) { fail(e); }
};
window.delRule = async (id) => {
  if (!confirm("Удалить правило?")) return;
  try { await api("DELETE", `/rules/${id}`); viewSettings(); } catch (e) { fail(e); }
};
window.resetRules = async () => {
  if (!confirm("Вернуть стандартную таблицу баллов?")) return;
  try { await api("POST", "/rules/reset"); toast("Стандартная таблица восстановлена"); viewSettings(); } catch (e) { fail(e); }
};

// ---------- источник слов ----------
function viewSource() {
  setView(`<h2>🌐 Источник слов</h2>
    <div class="card">
      <button class="block" onclick="loadBundled()">📘 Словарь Navigate B1+ (Unit 1–12)</button>
    </div>
    <div class="card"><h3>Ссылка на сайт</h3>
      <input id="src-url" placeholder="https://...">
      <button class="block" onclick="loadUrl()">Загрузить по ссылке</button>
    </div>
    <div class="card"><h3>Ввести вручную</h3>
      <textarea id="src-text" placeholder="apple - яблоко&#10;cat - кот"></textarea>
      <button class="block" onclick="loadManual()">Добавить в раздел «Мои»</button>
    </div>`);
}
window.loadBundled = async () => {
  try { const r = await api("POST", "/source/bundled"); toast(`Загружено: ${r.loaded} (новых ${r.added})`); go("train"); } catch (e) { fail(e); }
};
window.loadUrl = async () => {
  try {
    const r = await api("POST", "/source/url", { url: document.getElementById("src-url").value.trim() });
    toast(`Загружено слов: ${r.loaded}`); go("train");
  } catch (e) { fail(e); }
};
window.loadManual = async () => {
  try {
    const r = await api("POST", "/source/manual", { text: document.getElementById("src-text").value });
    toast(`Добавлено: ${r.added}` + (r.bad.length ? `, не распознано строк: ${r.bad.length}` : ""));
  } catch (e) { fail(e); }
};

// ---------- маршрутизация ----------
const ROUTES = {
  home: viewHome, train: viewTrain, words: viewWords, stats: viewStats,
  points: viewPoints, settings: viewSettings, source: viewSource,
};
async function route() {
  const name = (location.hash || "#home").slice(1);
  const view = ROUTES[name] || viewHome;
  try { await view(); } catch (e) { fail(e); setView(`<p class="muted">Не удалось загрузить раздел.</p><a class="btn" href="#home">Главное меню</a>`); }
}
window.addEventListener("hashchange", route);
route();
