// Render driver: loads scene.html in headless Chromium, steps time frame-by-frame,
// and pipes JPEG frames into ffmpeg. Parallel workers each encode a segment.
//   node src/render.js preview 1.0 4.5 ...   → build/preview_<t>.png
//   node src/render.js full [workers]        → build/video_noaudio.mp4
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), { spawn, execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '..'), B = path.join(ROOT, 'build');
const J = f => JSON.parse(fs.readFileSync(path.join(B, f)));
const data = { tl: J('timeline.json'), words: J('words.json'), vis: J('visemes.json'), lines: J('lines.json') };
const FPS = 30;

async function openPage(browser){
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.error('PAGE ERROR', e.message));
  await page.goto('file://' + path.join(ROOT, 'src', 'scene.html'));
  await page.evaluate(d => window.init(d), data);
  return page;
}
async function frameJpeg(page, t){
  const b64 = await page.evaluate(t => { window.renderAt(t); return document.getElementById('c').toDataURL('image/jpeg', 0.95).slice(23); }, t);
  return Buffer.from(b64, 'base64');
}

async function preview(times){
  const browser = await chromium.launch();
  const page = await openPage(browser);
  for (const t of times){
    const buf = await frameJpeg(page, t);
    fs.writeFileSync(path.join(B, `preview_${t.toFixed(2)}.jpg`), buf);
  }
  await browser.close();
}

async function segment(browser, idx, f0, f1){
  const page = await openPage(browser);
  const out = path.join(B, `seg_${idx}.mp4`);
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '14', '-pix_fmt', 'yuv420p', '-r', String(FPS), out]);
  for (let f = f0; f < f1; f++){
    const buf = await frameJpeg(page, f / FPS);
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - f0) % 60 === 0) console.log(`worker ${idx}: frame ${f}/${f1}`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await page.close();
  return out;
}

async function full(workers){
  const total = Math.round(data.tl.duration * FPS);
  const browser = await chromium.launch();
  const per = Math.ceil(total / workers);
  const segs = await Promise.all(Array.from({ length: workers }, (_, i) => segment(browser, i, i*per, Math.min(total, (i+1)*per))));
  await browser.close();
  const list = path.join(B, 'segs.txt');
  fs.writeFileSync(list, segs.map(s => `file '${s}'`).join('\n'));
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', path.join(B, 'video_noaudio.mp4')]);
  console.log('frames', total);
}

const [mode, ...args] = process.argv.slice(2);
if (mode === 'thumb') (async () => { const b = await chromium.launch(); const pg = await openPage(b);
  const b64 = await pg.evaluate(() => { window.renderThumb(); return document.getElementById('c').toDataURL('image/png').slice(22); });
  fs.writeFileSync(path.join(ROOT, 'out', 'thumbnail.png'), Buffer.from(b64, 'base64')); await b.close(); })();
else if (mode === 'preview') preview(args.map(Number)).catch(e => { console.error(e); process.exit(1); });
else full(Number(args[0] || 4)).catch(e => { console.error(e); process.exit(1); });
