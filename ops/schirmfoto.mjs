// Schirmfoto per DevTools-Protokoll - das Werkzeug für die HINSEHEN-Pflicht.
//
// WARUM NICHT `chrome --headless --screenshot --window-size=390,844`:
// Gemessen am 24.08.2026 klemmt Headless-Chrome die Fensterbreite bei rund 500 px.
// Ein so entstandenes "390-px-Bild" ist in Wahrheit ein auf 390 px BESCHNITTENES
// 485-px-Layout - zwei UI-Befunde dieser Sitzung waren dadurch Phantome. Nur
// `Emulation.setDeviceMetricsOverride` setzt die Breite wirklich; deshalb dieser Weg.
//
//   node ops/schirmfoto.mjs <url> <ziel.png> [--breite 390] [--hoehe 844] [--dpr 2]
//        [--theme dark|light] [--warten 1500] [--klick "Text der Taste"] [--danach 1200]
//        [--ganz]   ganze Seite statt nur des Sichtfensters
//        [--scrollen]  vorher durch die Seite rollen (Reveals, lazy-Bilder)
//        [--js "<Ausdruck>"]  JS auswerten und Ergebnis ausgeben
//
// --klick sucht eine Taste/einen Knopf mit genau diesem Text und drückt sie. So
// lassen sich Zustände fotografieren, die erst nach einer Handlung entstehen
// (Pop-up, zweiter Schritt) - ohne Erweiterung, ohne Puppeteer.
import { spawn } from 'node:child_process';
import { writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const argv = process.argv.slice(2);
const wert = (name, vorgabe) => { const i = argv.indexOf(`--${name}`); return i >= 0 && argv[i + 1] ? argv[i + 1] : vorgabe; };
// Erst die Schalter mit Wert markieren, dann bleibt der Rest als Stellung uebrig.
// (Ein `argv.filter` mit indexOf ist hier falsch: indexOf findet bei gleichen
// Zeichenketten immer die erste Stelle - gemessen an "--theme light".)
const MIT_WERT = new Set(['breite', 'hoehe', 'dpr', 'theme', 'warten', 'klick', 'danach', 'js']);
const stellung = [];
for (let i = 0; i < argv.length; i += 1) {
  const a = argv[i];
  if (a.startsWith('--')) { if (MIT_WERT.has(a.slice(2))) i += 1; continue; }
  stellung.push(a);
}
const [url, ziel] = stellung;
if (!url || !ziel) {
  console.error('Aufruf: node ops/schirmfoto.mjs <url> <ziel.png> [--breite 390] [--theme dark] [--klick "Text"]');
  process.exit(64);
}
const BREITE = Number(wert('breite', 1280));
const HOEHE = Number(wert('hoehe', 900));
const DPR = Number(wert('dpr', 2));
const THEME = wert('theme', null);
const WARTEN = Number(wert('warten', 1500));
const DANACH = Number(wert('danach', 1200));
const KLICK = wert('klick', null);
const GANZ = argv.includes('--ganz');
// --scrollen: vor der Aufnahme schrittweise durch die Seite rollen (ScrollTrigger-Reveals,
// lazy-Bilder). Ohne das bleibt bei --ganz alles unsichtbar, was erst beim Rollen erscheint
// (gemessen 01.09.2026 an sundsconnect.de: Startseite unterhalb der Kennzahlen leer).
const SCROLLEN = argv.includes('--scrollen');
const CHROME = process.env.CHROME_PFAD
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const schlaf = (ms) => new Promise((f) => setTimeout(f, ms));

const profil = await mkdtemp(join(tmpdir(), 'schirm-'));
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profil}`,
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--hide-scrollbars', '--force-device-scale-factor=1', 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });

// Chrome schreibt den gewählten Port auf stderr ("DevTools listening on ws://...").
const wsBasis = await new Promise((fertig, scheitern) => {
  let puffer = '';
  const uhr = setTimeout(() => scheitern(new Error('Chrome meldete binnen 20 s keinen DevTools-Port')), 20_000);
  chrome.stderr.on('data', (t) => {
    puffer += t.toString();
    const m = /DevTools listening on (ws:\/\/[^\s]+)/.exec(puffer);
    if (m) { clearTimeout(uhr); fertig(m[1]); }
  });
  chrome.on('exit', (c) => { clearTimeout(uhr); scheitern(new Error(`Chrome beendete sich mit ${c}`)); });
});
const port = new URL(wsBasis).port;

// Eine Seite (Ziel) holen und daran anschließen.
const seiten = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const seite = seiten.find((s) => s.type === 'page');
const ws = new WebSocket(seite.webSocketDebuggerUrl);
await new Promise((f, s) => { ws.onopen = f; ws.onerror = s; });

let lfd = 0;
const offen = new Map();
ws.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.id && offen.has(d.id)) {
    const { fertig, scheitern } = offen.get(d.id); offen.delete(d.id);
    if (d.error) scheitern(new Error(`${d.error.message}`)); else fertig(d.result);
  }
};
const cdp = (methode, params = {}) => new Promise((fertig, scheitern) => {
  const id = ++lfd; offen.set(id, { fertig, scheitern });
  ws.send(JSON.stringify({ id, method: methode, params }));
  setTimeout(() => { if (offen.has(id)) { offen.delete(id); scheitern(new Error(`${methode}: keine Antwort`)); } }, 30_000);
});

try {
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Log.enable').catch(() => {});
  // Konsole mitschreiben: ein Bild zeigt, WAS zu sehen ist - der Fehler dahinter
  // steht in der Konsole (gemessen 25.08.: das Pop-up fehlte im Bild, die Ursache
  // stand als eine Zeile im Log).
  const meldungen = [];
  ws.addEventListener('message', (e) => {
    const d = JSON.parse(e.data);
    if (d.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(d.params.type)) {
      meldungen.push(`[${d.params.type}] ` + (d.params.args ?? []).map((a) => a.value ?? a.description ?? a.type).join(' '));
    }
    if (d.method === 'Runtime.exceptionThrown') {
      meldungen.push('[ausnahme] ' + (d.params.exceptionDetails?.exception?.description ?? d.params.exceptionDetails?.text));
    }
    if (d.method === 'Log.entryAdded' && d.params.entry.level === 'error') {
      meldungen.push('[netz] ' + d.params.entry.text + ' ' + (d.params.entry.url ?? ''));
    }
  });
  // DAS ist der Unterschied zu --window-size: echte Gerätemaße statt Beschnitt.
  await cdp('Emulation.setDeviceMetricsOverride', {
    width: BREITE, height: HOEHE, deviceScaleFactor: DPR, mobile: BREITE < 700,
  });
  if (THEME) await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: THEME }] });

  await cdp('Page.navigate', { url });
  await schlaf(WARTEN);

  if (SCROLLEN) {
    await cdp('Runtime.evaluate', {
      expression: `(async () => {
        const h = () => document.documentElement.scrollHeight;
        for (let y = 0; y < h(); y += Math.round(innerHeight * 0.6)) {
          window.scrollTo(0, y); await new Promise((f) => setTimeout(f, 120));
        }
        window.scrollTo(0, h()); await new Promise((f) => setTimeout(f, 300));
        window.scrollTo(0, 0); await new Promise((f) => setTimeout(f, 200));
        return h();
      })()`,
      awaitPromise: true, returnByValue: true,
    });
    await schlaf(DANACH);
  }

  if (KLICK) {
    const r = await cdp('Runtime.evaluate', {
      expression: `(() => {
        const t = ${JSON.stringify(KLICK)};
        const k = [...document.querySelectorAll('button, a, .taste')].find((x) => (x.textContent || '').trim() === t);
        if (!k) return 'nicht gefunden: ' + t;
        k.click(); return 'geklickt: ' + t;
      })()`,
      returnByValue: true,
    });
    console.log('  ' + r.result.value);
    await schlaf(DANACH);
  }

  // --ganz: CDP kennt kein "clip: null" (gemessen 26.08.2026: "Invalid parameters",
  // die Option war seit dem Bau wirkungslos). Ganze Seite = Inhaltsmasse abfragen
  // und als Clip mitgeben, dazu captureBeyondViewport.
  let clip;
  if (GANZ) {
    const m = await cdp('Page.getLayoutMetrics');
    const g = m.cssContentSize ?? m.contentSize;
    clip = { x: 0, y: 0, width: Math.ceil(g.width), height: Math.ceil(g.height), scale: 1 };
  }
  // --js: Ausdruck auswerten und als JSON ausgeben (Messwerte statt Vermutung).
  const JSX = wert('js', null);
  if (JSX) {
    const r = await cdp('Runtime.evaluate', { expression: JSX, awaitPromise: true, returnByValue: true });
    console.log('js: ' + JSON.stringify(r.result.value ?? r.result.description ?? r.result));
  }
  const bild = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: GANZ, ...(clip ? { clip } : {}) });
  await writeFile(ziel, Buffer.from(bild.data, 'base64'));
  console.log(`geschrieben: ${ziel} (${BREITE}x${HOEHE}, dpr ${DPR}${THEME ? ', theme ' + THEME : ''})`);
  if (meldungen.length) {
    console.log(`Konsole (${meldungen.length}):`);
    for (const m of meldungen.slice(0, 15)) console.log('  ' + m.slice(0, 200));
  }
} finally {
  ws.close();
  chrome.kill();
  await rm(profil, { recursive: true, force: true }).catch(() => {});
}
