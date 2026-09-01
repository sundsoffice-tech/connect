// fernchrome.mjs - ein sichtbares Chrome-Fenster starten und per DevTools-Protokoll steuern.
//
// WARUM: Die Claude-Chrome-Erweiterung haengt am claude.ai-Konto; nach einem Kontowechsel
// ist sie nicht mehr gekoppelt (gemessen 01.09.2026: list_connected_browsers = []). Dieses
// Werkzeug braucht keine Erweiterung: eigenes Chrome mit eigenem Profil, fester Port, der
// Mensch tippt Zugangsdaten selbst ins Fenster, die Session steuert danach Klicks und liest.
//
//   node ops/fernchrome.mjs start <url>        Chrome sichtbar starten (Port 9333, Wegwerf-Profil)
//   node ops/fernchrome.mjs goto <url>
//   node ops/fernchrome.mjs shot <ziel.png>    Bildschirmfoto des Sichtfensters (1 CSS-px = 1 px)
//   node ops/fernchrome.mjs js "<Ausdruck>"    auswerten, Ergebnis als JSON
//   node ops/fernchrome.mjs click <x> <y>      Mausklick in CSS-Pixeln des Sichtfensters
//   node ops/fernchrome.mjs type "<Text>"      Text in das fokussierte Feld
//   node ops/fernchrome.mjs key <Enter|Tab|Escape|Backspace>
//   node ops/fernchrome.mjs tabs               offene Seiten
//   node ops/fernchrome.mjs stop
//
// Zugangsdaten werden hier NIE eingegeben; "type" ist fuer Formularwerte wie IP-Adressen.
import { spawn } from 'node:child_process';
import { writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const PORT = Number(process.env.FERNCHROME_PORT || 9333);
const PROFIL = process.env.FERNCHROME_PROFIL || join(tmpdir(), 'fernchrome-profil');
const CHROME = process.env.CHROME_PFAD || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const [befehl, ...rest] = process.argv.slice(2);
const schlaf = (ms) => new Promise((f) => setTimeout(f, ms));

async function version() {
  try { return await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch { return null; }
}

async function start(url) {
  if (await version()) { console.log(`laeuft schon auf Port ${PORT}`); if (url) await goto(url); return; }
  if (!existsSync(PROFIL)) await mkdir(PROFIL, { recursive: true });
  const kind = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFIL}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--force-device-scale-factor=1', '--window-size=1400,1000', '--window-position=40,40',
    '--lang=de-DE', url || 'about:blank',
  ], { detached: true, stdio: 'ignore' });
  kind.unref();
  for (let i = 0; i < 60; i += 1) { await schlaf(500); if (await version()) break; }
  const v = await version();
  if (!v) throw new Error('Chrome meldete sich binnen 30 s nicht');
  console.log(`gestartet: ${v.Browser}, Port ${PORT}, Profil ${PROFIL}`);
}

async function seite() {
  const liste = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const s = liste.find((t) => t.type === 'page' && !t.url.startsWith('devtools://'));
  if (!s) throw new Error('keine Seite gefunden');
  return s;
}

async function verbinde() {
  const s = await seite();
  const ws = new WebSocket(s.webSocketDebuggerUrl);
  await new Promise((f, r) => { ws.onopen = f; ws.onerror = r; });
  let lfd = 0; const offen = new Map();
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.id && offen.has(d.id)) { const { f, r } = offen.get(d.id); offen.delete(d.id); d.error ? r(new Error(d.error.message)) : f(d.result); }
  };
  const cdp = (m, p = {}) => new Promise((f, r) => {
    const id = ++lfd; offen.set(id, { f, r }); ws.send(JSON.stringify({ id, method: m, params: p }));
    setTimeout(() => { if (offen.has(id)) { offen.delete(id); r(new Error(`${m}: keine Antwort`)); } }, 30_000);
  });
  return { cdp, ws, s };
}

async function goto(url) {
  const { cdp, ws } = await verbinde();
  await cdp('Page.enable'); await cdp('Page.navigate', { url }); await schlaf(1500);
  const r = await cdp('Runtime.evaluate', { expression: 'document.title + " | " + location.href', returnByValue: true });
  console.log(r.result.value); ws.close();
}

async function shot(ziel) {
  const { cdp, ws } = await verbinde();
  // Ohne Vordergrund liefert Chrome fuer verdeckte Tabs kein Bild (30 s keine Antwort, gemessen 01.09.2026)
  await cdp('Page.bringToFront').catch(() => {});
  const m = await cdp('Page.getLayoutMetrics');
  const bild = await cdp('Page.captureScreenshot', { format: 'png' });
  await writeFile(ziel, Buffer.from(bild.data, 'base64'));
  const r = await cdp('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
  console.log(`geschrieben: ${ziel} (${Math.round(m.cssVisualViewport.clientWidth)}x${Math.round(m.cssVisualViewport.clientHeight)}, scroll ${Math.round(m.cssVisualViewport.pageY)}) ${r.result.value}`);
  ws.close();
}

async function js(ausdruck) {
  const { cdp, ws } = await verbinde();
  const r = await cdp('Runtime.evaluate', { expression: ausdruck, awaitPromise: true, returnByValue: true });
  console.log(JSON.stringify(r.result.value ?? r.result.description ?? r.exceptionDetails ?? r.result));
  ws.close();
}

async function click(x, y) {
  const { cdp, ws } = await verbinde();
  const p = { x: Number(x), y: Number(y), button: 'left', clickCount: 1 };
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', ...p });
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', ...p });
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', ...p });
  await schlaf(400); console.log(`geklickt ${x},${y}`); ws.close();
}

async function type(text) {
  const { cdp, ws } = await verbinde();
  await cdp('Input.insertText', { text }); await schlaf(200);
  console.log(`getippt (${text.length} Zeichen)`); ws.close();
}

async function key(name) {
  const { cdp, ws } = await verbinde();
  const codes = { Enter: 13, Tab: 9, Escape: 27, Backspace: 8, Delete: 46, ArrowDown: 40, ArrowUp: 38 };
  const code = codes[name]; if (!code) throw new Error('unbekannte Taste ' + name);
  const basis = { key: name, code: name, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', ...basis, ...(name === 'Enter' ? { text: '\r' } : {}) });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', ...basis });
  await schlaf(300); console.log(`Taste ${name}`); ws.close();
}

async function tabs() {
  const liste = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  for (const t of liste.filter((x) => x.type === 'page')) console.log(`${t.title} | ${t.url}`);
}

async function stop() {
  const v = await version(); if (!v) { console.log('laeuft nicht'); return; }
  const ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((f, r) => { ws.onopen = f; ws.onerror = r; });
  ws.send(JSON.stringify({ id: 1, method: 'Browser.close' })); await schlaf(500); ws.close();
  console.log('beendet');
}

const befehle = { start, goto, shot, js, click, type, key, tabs, stop };
if (!befehle[befehl]) { console.error('Aufruf: node ops/fernchrome.mjs start|goto|shot|js|click|type|key|tabs|stop ...'); process.exit(64); }
// Ausdruecklich beenden: ein offener WebSocket haelt Node sonst bis zu einer Minute am Leben (gemessen 01.09.2026).
try { await befehle[befehl](...rest); process.exit(0); } catch (e) { console.error('Fehler: ' + e.message); process.exit(1); }
