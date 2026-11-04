// Frame-accurate renderer: drives src/index.html with an explicit clock (no
// realtime animation), screenshots every frame and pipes PNGs into ffmpeg.
// usage: node src/render.js video [fps] [workers]   -> build/video_noaudio.mp4 + build/events.json
//        node src/render.js stills t1 t2 ...        -> build/stills/t_XX.png
//        node src/render.js thumb                   -> output/thumbnail.png
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..'), BUILD = path.join(ROOT, 'build');
const data = JSON.parse(fs.readFileSync(path.join(BUILD, 'timeline.json')));
const PAGE = 'file://' + path.join(__dirname, 'film.html');

async function open(browser, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('PAGE ERROR', e); process.exit(1); });
  await page.goto(PAGE); await page.evaluate(() => document.fonts.ready);
  const info = await page.evaluate(([d, o]) => window.__init(d, o), [data, opts]);
  await page.evaluate(() => document.fonts.ready);
  return { page, info };
}

async function main() {
  const [mode, ...args] = process.argv.slice(2);
  const browser = await chromium.launch();
  if (mode === 'stills') {
    fs.mkdirSync(path.join(BUILD, 'stills'), { recursive: true });
    const { page } = await open(browser);
    for (const a of args) { const t = +a; await page.evaluate(t => window.__render(t), t);
      await page.screenshot({ path: path.join(BUILD, 'stills', `t_${t.toFixed(2)}.png`) }); }
  } else if (mode === 'thumb') {
    const { page } = await open(browser);
    await page.evaluate(t => window.__thumb(t), +(args[0] || 0));
    await page.screenshot({ path: path.join(ROOT, 'output', 'thumbnail.png') });
  } else {
    const fps = +(args[0] || 30), workers = +(args[1] || 4), NSEG = 24;
    const { info } = await open(browser);
    fs.writeFileSync(path.join(BUILD, 'events.json'), JSON.stringify(info, null, 1));
    const N = Math.ceil(info.duration * fps), per = Math.ceil(N / NSEG), t0 = Date.now();
    const segs = [...Array(NSEG).keys()].filter(k => k * per < N);
    const todo = segs.filter(k => !fs.existsSync(path.join(BUILD, `part_${k}.mp4`)));
    console.log('segments to render', todo.length, 'of', segs.length);
    let q = 0;
    await Promise.all([...Array(workers).keys()].map(async () => {
      const { page } = await open(browser);
      while (q < todo.length) {
        const k = todo[q++], a = k * per, b = Math.min(N, a + per), tmp = path.join(BUILD, `part_${k}.tmp.mp4`);
        const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-i', '-',
          '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(fps), tmp], { stdio: ['pipe', 'inherit', 'inherit'] });
        for (let f = a; f < b; f++) {
          await page.evaluate(t => window.__render(t), f / fps);
          const buf = await page.screenshot({ type: 'jpeg', quality: 95 });
          if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
        }
        ff.stdin.end(); await new Promise(r => ff.on('close', r));
        fs.renameSync(tmp, path.join(BUILD, `part_${k}.mp4`));
        console.log(`segment ${k} done (${b}/${N})  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
      }
    }));
    fs.writeFileSync(path.join(BUILD, 'segs.txt'), segs.map(k => `file '${path.join(BUILD, `part_${k}.mp4`)}'`).join('\n'));
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(BUILD, 'segs.txt'), '-c', 'copy', path.join(BUILD, 'video_noaudio.mp4')]);
    console.log('frames', N, 'time', (Date.now() - t0) / 1000);
  }
  await browser.close();
}
main();
