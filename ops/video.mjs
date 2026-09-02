// video.mjs - deterministisches Frame-Rendern einer Zeitleisten-Seite (window.seek(ms)).
//
//   node ops/video.mjs <url> <framedir> [--fps 30] [--breite 1920] [--hoehe 1080]
//        [--von 0] [--bis DAUER] [--schritt 1]   (--schritt 5 = jeden 5. Frame, fuer Proben)
//
// Die Seite muss window.seek(ms) und window.DAUER bereitstellen. Jeder Frame wird als
// JPEG (Qualitaet 92) geschrieben; zusammensetzen macht ffmpeg ausserhalb.
import { spawn } from 'node:child_process';
import { writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtempSync } from 'node:fs';

const argv = process.argv.slice(2);
const wert = (n, v) => { const i = argv.indexOf(`--${n}`); return i >= 0 && argv[i + 1] ? argv[i + 1] : v; };
const [url, framedir] = argv.filter(a => !a.startsWith('--')).filter((a, i, arr) => {
  const idx = argv.indexOf(a); return idx === 0 || !argv[idx - 1].startsWith('--');
});
if (!url || !framedir) { console.error('Aufruf: node ops/video.mjs <url> <framedir> [--fps 30] ...'); process.exit(64); }
const FPS = Number(wert('fps', 30));
const BREITE = Number(wert('breite', 1920));
const HOEHE = Number(wert('hoehe', 1080));
const SCHRITT = Number(wert('schritt', 1));
const VON = Number(wert('von', 0));
const CHROME = process.env.CHROME_PFAD || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const schlaf = (ms) => new Promise((f) => setTimeout(f, ms));

await mkdir(framedir, { recursive: true });
const profil = mkdtempSync(join(tmpdir(), 'video-'));
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profil}`,
  '--no-first-run', '--disable-extensions', '--hide-scrollbars',
  '--force-device-scale-factor=1', '--disable-lcd-text', 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
const wsBasis = await new Promise((fertig, scheitern) => {
  let puffer = '';
  const uhr = setTimeout(() => scheitern(new Error('kein DevTools-Port binnen 20 s')), 20000);
  chrome.stderr.on('data', (t) => {
    puffer += t.toString();
    const m = /DevTools listening on (ws:\/\/\S+)/.exec(puffer);
    if (m) { clearTimeout(uhr); fertig(m[1]); }
  });
});
const port = new URL(wsBasis).port;
const seiten = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(seiten.find((s) => s.type === 'page').webSocketDebuggerUrl);
await new Promise((f, r) => { ws.onopen = f; ws.onerror = r; });
let lfd = 0; const offen = new Map();
ws.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.id && offen.has(d.id)) { const { f, r } = offen.get(d.id); offen.delete(d.id); d.error ? r(new Error(d.error.message)) : f(d.result); }
};
const cdp = (m, p = {}) => new Promise((f, r) => {
  const id = ++lfd; offen.set(id, { f, r }); ws.send(JSON.stringify({ id, method: m, params: p }));
  setTimeout(() => { if (offen.has(id)) { offen.delete(id); r(new Error(`${m}: keine Antwort`)); } }, 30000);
});

try {
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: BREITE, height: HOEHE, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url });
  await schlaf(1200);
  const bereit = await cdp('Runtime.evaluate', {
    expression: 'document.fonts.ready.then(() => typeof window.seek === "function" ? window.DAUER : -1)',
    awaitPromise: true, returnByValue: true,
  });
  const DAUER = bereit.result.value;
  if (DAUER < 0) throw new Error('Seite hat kein window.seek');
  const BIS = Number(wert('bis', DAUER));
  const gesamt = Math.floor((BIS - VON) / 1000 * FPS);
  console.log(`Dauer ${DAUER} ms, ${FPS} fps, Frames ${VON / 1000 * FPS} bis ${gesamt} (Schritt ${SCHRITT})`);
  const t0 = Date.now();
  for (let i = Math.floor(VON / 1000 * FPS); i < gesamt; i += SCHRITT) {
    const ms = i * 1000 / FPS;
    await cdp('Runtime.evaluate', { expression: `seek(${ms})`, returnByValue: true });
    const bild = await cdp('Page.captureScreenshot', { format: 'jpeg', quality: 92 });
    await writeFile(join(framedir, `f${String(i).padStart(5, '0')}.jpg`), Buffer.from(bild.data, 'base64'));
    if (i % (FPS * 5) === 0) console.log(`  Frame ${i}/${gesamt} (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  }
  console.log(`fertig: ${gesamt} Frames in ${((Date.now() - t0) / 1000).toFixed(0)} s -> ${framedir}`);
} finally {
  ws.close(); chrome.kill();
}
process.exit(0);
