:root {
  --bg: var(--tg-theme-bg-color, #f4f6fb);
  --text: var(--tg-theme-text-color, #1d2330);
  --hint: var(--tg-theme-hint-color, #7a8294);
  --accent: var(--tg-theme-button-color, #3b82f6);
  --accent-text: var(--tg-theme-button-text-color, #ffffff);
  --card: var(--tg-theme-secondary-bg-color, #ffffff);
  --ok: #22c55e; --bad: #ef4444;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg); color: var(--text); padding-bottom: env(safe-area-inset-bottom, 0); }
.top { padding: 14px 16px 6px; }
.brand { font-weight: 700; font-size: 18px; color: var(--text); text-decoration: none; }
main { padding: 8px 14px 40px; max-width: 620px; margin: 0 auto; }
h2 { margin: 12px 0 10px; font-size: 20px; }
h3 { margin: 14px 0 8px; font-size: 16px; }
.muted { color: var(--hint); font-size: 14px; }
.card { background: var(--card); border-radius: 16px; padding: 14px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tile { background: var(--card); border-radius: 16px; padding: 18px 10px; text-align: center; text-decoration: none; color: var(--text); font-size: 15px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.tile .ico { font-size: 28px; display: block; margin-bottom: 6px; }
button, .btn { font: inherit; border: 0; border-radius: 12px; padding: 12px 14px; background: var(--accent); color: var(--accent-text); cursor: pointer; font-size: 15px; }
button.secondary { background: var(--card); color: var(--text); border: 1px solid rgba(127,127,127,.25); }
button.danger { background: var(--bad); }
button:disabled { opacity: .5; }
button.block { width: 100%; margin: 6px 0; }
input, select, textarea { font: inherit; width: 100%; padding: 11px 12px; border-radius: 12px; border: 1px solid rgba(127,127,127,.3); background: var(--bg); color: var(--text); margin: 4px 0; }
textarea { min-height: 110px; }
.row { display: flex; gap: 8px; align-items: center; }
.row > * { flex: 1; }
.row > .auto { flex: 0 0 auto; }
.list-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 0; border-bottom: 1px solid rgba(127,127,127,.15); }
.list-item:last-child { border-bottom: 0; }
.bar { height: 10px; border-radius: 6px; background: rgba(127,127,127,.2); overflow: hidden; margin: 8px 0; }
.bar > div { height: 100%; background: var(--accent); transition: width .3s; }
.word-card { text-align: center; padding: 26px 14px; }
.word-card .big { font-size: 34px; margin: 10px 0; font-weight: 700; }
.mic { width: 96px; height: 96px; border-radius: 50%; font-size: 40px; padding: 0; margin: 10px auto; display: block; }
.mic.rec { background: var(--bad); }
.feedback { padding: 12px; border-radius: 14px; margin-top: 10px; }
.feedback.ok { background: rgba(34,197,94,.15); }
.feedback.bad { background: rgba(239,68,68,.15); }
.stat { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(127,127,127,.12); }
.toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: #111827; color: #fff; padding: 10px 16px; border-radius: 12px; font-size: 14px; z-index: 9; max-width: 90%; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 10px; background: rgba(127,127,127,.15); font-size: 13px; }
