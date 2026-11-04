// ───────────── Character rig (SVG, 2.5D) ─────────────
// One rig drives every character so designs stay identical between shots.
// Units: px at scale 1, origin = hip centre.  Head centre (0,-345).
const NS = 'http://www.w3.org/2000/svg';
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, x) => a + (b - a) * x;
const p01 = (t, a, b) => clamp((t - a) / (b - a));
const sstep = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const eo = x => 1 - Math.pow(1 - clamp(x), 3);
const eio = x => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eob = x => { x = clamp(x); const c1 = 1.7, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
function hash(i) { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
function noise(t, seed) { // smooth value noise in [-1,1]
  const i = Math.floor(t), f = t - i, u = f * f * (3 - 2 * f);
  return lerp(hash(i + seed * 57.3), hash(i + 1 + seed * 57.3), u) * 2 - 1;
}

// viseme targets: o=open, w=wide, r=round, c=closed(lip press), f=lower lip to teeth
const V = {};
const setV = (chars, v) => [...chars].forEach(c => V[c] = v);
setV('aɑɐæʌ', { o: .85, w: .55, r: 0 });
setV('ɛe', { o: .55, w: .75, r: 0 });
setV('iɪjᵻ', { o: .25, w: .95, r: 0 });
setV('oɔɒ', { o: .65, w: .3, r: .75 });
setV('uʊwɵ', { o: .28, w: .15, r: 1 });
setV('əɚɜ', { o: .42, w: .5, r: .1 });
setV('pbm', { o: 0, w: .45, r: 0, c: 1 });
setV('fv', { o: .08, w: .55, r: 0, f: 1 });
setV('θð', { o: .2, w: .55, r: 0 });
setV('stdnlrɹɾzkɡŋxhʔ', { o: .2, w: .62, r: 0 });
setV('ʃʒʧʤ', { o: .25, w: .35, r: .55 });
const REST = { o: 0, w: .5, r: 0, c: 0, f: 0 };

function visemeAt(phones, t) {
  // gaussian-weighted blend of nearby phoneme targets (co-articulation)
  if (!phones || !phones.length || t < phones[0][1] - .12 || t > phones[phones.length - 1][2] + .12) return null;
  let acc = { o: 0, w: 0, r: 0, c: 0, f: 0 }, W = 0;
  for (const [ch, s, e] of phones) {
    const m = (s + e) / 2; const d = t - m; if (Math.abs(d) > .16) continue;
    const sig = Math.max(.03, (e - s) * .55); const wgt = Math.exp(-d * d / (2 * sig * sig));
    const v = V[ch] || { o: .25, w: .55, r: 0 };
    for (const k in acc) acc[k] += (v[k] || 0) * wgt; W += wgt;
  }
  // fade to rest at boundaries
  const fadeIn = p01(t, phones[0][1] - .06, phones[0][1] + .02), fadeOut = 1 - p01(t, phones[phones.length - 1][2] - .02, phones[phones.length - 1][2] + .1);
  const k = Math.min(fadeIn, fadeOut);
  if (!W) return null;
  for (const n in acc) acc[n] = lerp(REST[n], acc[n] / W, k);
  return acc;
}

const LOOKS = {
  RU: { gender: 'm', skin: '#EFC6A4', skinSh: '#D9A27F', hair: '#8A6440', hairHi: '#B08A5E', style: 'side', eye: '#5B87A8', brow: '#6B4A2E',
    suit: '#18213A', suitHi: '#26314F', shirt: '#F4F5F7', tie: '#0B1020', tieHi: '#2E3B63', lip: '#C38677', watch: 'silver', jaw: 'square', stubble: 0.08 },
  IT: { gender: 'm', skin: '#D8A07A', skinSh: '#B97F5A', hair: '#1E120C', hairHi: '#4A3122', style: 'slick', eye: '#5A3A22', brow: '#1E120C',
    suit: '#5C1A2A', suitHi: '#7A2638', shirt: '#121212', tie: null, lip: '#A86A5A', watch: 'gold', jaw: 'square', stubble: 0.35, chain: true, pocket: '#E9B949' },
  GF: { gender: 'f', skin: '#EBBF9C', skinSh: '#D49E7B', hair: '#4A2014', hairHi: '#7A3A22', style: 'long', eye: '#3F6B4E', brow: '#3A1C12',
    dress: '#0F6B52', dressHi: '#1B8A6B', lip: '#B5203A', earrings: true, necklace: true },
};

class Char {
  constructor(id, look, parent, opts = {}) {
    this.id = id; this.L = look; this.detail = opts.detail ?? 1; this.noArms = !!opts.armsParent;
    const g = document.createElementNS(NS, 'g'); g.id = id; parent.appendChild(g); this.g = g;
    g.innerHTML = this.svg(); this.r = {};
    if (opts.armsParent) {
      const ga = document.createElementNS(NS, 'g'); ga.id = id + '-arms'; opts.armsParent.appendChild(ga); this.ga = ga;
      ga.innerHTML = `<g data-r="aroot"><g data-r="abody">${this.armSVG('L')}${this.armSVG('R')}</g></g>`;
      for (const el of ga.querySelectorAll('[data-r]')) this.r[el.dataset.r] = el;
    }
    for (const el of g.querySelectorAll('[data-r]')) if (!this.r[el.dataset.r]) this.r[el.dataset.r] = el;
    this.handL = { x: -75, y: -62 }; this.handR = { x: 75, y: -62 };
  }
  svg() {
    const L = this.L, id = this.id, f = L.gender === 'f';
    const sh = f ? 80 : 106; // shoulder half width
    const torso = f
      ? `<path d="M -${sh},-222 C -86,-150 -70,-70 -66,0 L 66,0 C 70,-70 86,-150 ${sh},-222 C 52,-238 28,-240 0,-238 C -28,-240 -52,-238 -${sh},-222 Z" fill="url(#${id}-skinG)"/>
         <path d="M -70,-206 C -64,-150 -66,-80 -68,0 L 68,0 C 66,-80 64,-150 70,-206 C 50,-196 26,-150 0,-128 C -26,-150 -50,-196 -70,-206 Z" fill="url(#${id}-dressG)"/>
         <path d="M -70,-206 L -62,-228 M 70,-206 L 62,-228" stroke="${L.dress}" stroke-width="4"/>
         <path d="M -40,-120 C -20,-100 20,-100 40,-120" stroke="${L.dressHi}" stroke-width="3" fill="none" opacity=".6"/>`
      : `<path d="M -${sh},-222 C -118,-160 -100,-60 -88,0 L 88,0 C 100,-60 118,-160 ${sh},-222 C 70,-246 30,-250 0,-248 C -30,-250 -70,-246 -${sh},-222 Z" fill="url(#${id}-suitG)"/>
         <path d="M -34,-248 L 0,-140 L 34,-248 Z" fill="${L.shirt}"/>
         ${L.tie ? `<path d="M -9,-238 L 9,-238 L 14,-158 L 0,-136 L -14,-158 Z" fill="${L.tie}"/><path d="M -10,-244 L 10,-244 L 8,-230 L -8,-230 Z" fill="${L.tieHi}"/><rect x="-16" y="-190" width="32" height="4" fill="#C9CED8"/>`
               : `<path d="M -18,-248 L 0,-200 L 18,-248 Z" fill="url(#${id}-skinG)"/>${L.chain ? `<path d="M -16,-244 C -10,-214 10,-214 16,-244" stroke="#E9C25A" stroke-width="3" fill="none"/>` : ''}`}
         <path d="M -38,-248 L -4,-140 L -22,-138 L -64,-228 Z" fill="${L.suitHi}"/><path d="M 38,-248 L 4,-140 L 22,-138 L 64,-228 Z" fill="${L.suitHi}"/>
         <path d="M -4,-140 L -2,0 M 4,-140 L 2,0" stroke="rgba(0,0,0,.25)" stroke-width="2"/>
         <circle cx="0" cy="-90" r="4" fill="rgba(0,0,0,.4)"/><circle cx="0" cy="-50" r="4" fill="rgba(0,0,0,.4)"/>
         ${L.pocket ? `<path d="M 50,-150 L 78,-154 L 74,-140 L 66,-146 L 58,-138 Z" fill="${L.pocket}"/>` : `<path d="M 50,-148 L 80,-150" stroke="rgba(255,255,255,.15)" stroke-width="3"/>`}`;
    const jaw = f
      ? 'M -52,-30 C -54,-82 -28,-104 0,-104 C 28,-104 54,-82 52,-30 C 52,6 42,34 26,54 C 16,66 8,70 0,70 C -8,70 -16,66 -26,54 C -42,34 -52,6 -52,-30 Z'
      : 'M -56,-30 C -58,-84 -30,-106 0,-106 C 30,-106 58,-84 56,-30 C 56,10 50,36 34,56 C 22,70 10,76 0,76 C -10,76 -22,70 -34,56 C -50,36 -56,10 -56,-30 Z';
    const hair = {
      side: { back: '', front: `<path d="M -60,-26 C -68,-92 -32,-122 4,-120 C 42,-120 68,-94 60,-30 C 58,-52 52,-64 44,-72 C 26,-88 -6,-90 -24,-82 C -40,-76 -54,-56 -60,-26 Z" fill="url(#${id}-hairG)"/>
              <path d="M -22,-116 C -30,-100 -32,-90 -30,-82" stroke="${L.hairHi}" stroke-width="3" fill="none" opacity=".7"/>
              <path d="M 0,-118 C 20,-112 40,-100 50,-80" stroke="${L.hairHi}" stroke-width="4" fill="none" opacity=".5"/>` },
      slick: { back: '', front: `<path d="M -60,-22 C -72,-104 -30,-140 8,-136 C 50,-134 74,-104 60,-24 C 60,-60 48,-80 30,-88 C 4,-98 -28,-94 -44,-78 C -54,-66 -58,-44 -60,-22 Z" fill="url(#${id}-hairG)"/>
              <path d="M -30,-126 C -6,-118 26,-114 50,-96 M -20,-132 C 6,-126 34,-120 56,-106" stroke="${L.hairHi}" stroke-width="3" fill="none" opacity=".8"/>` },
      long: { back: `<path d="M -66,-60 C -96,40 -104,110 -86,170 C -60,186 -36,176 -30,150 L 30,150 C 36,176 60,186 86,170 C 104,110 96,40 66,-60 C 60,-110 30,-126 0,-124 C -30,-126 -60,-110 -66,-60 Z" fill="url(#${id}-hairG)"/>`,
              front: `<path d="M -58,-10 C -66,-90 -30,-122 6,-120 C 44,-118 66,-88 58,-14 C 50,-60 34,-84 10,-90 C -2,-70 -22,-56 -48,-44 C -54,-34 -56,-22 -58,-10 Z" fill="url(#${id}-hairG)"/>
              <path d="M 10,-112 C 30,-104 46,-84 52,-56 M -40,-100 C -48,-80 -54,-56 -56,-30" stroke="${L.hairHi}" stroke-width="3.5" fill="none" opacity=".7"/>` },
      short: { back: '', front: `<path d="M -58,-30 C -64,-96 -28,-116 2,-114 C 34,-114 64,-96 58,-30 C 52,-72 30,-86 0,-86 C -28,-86 -52,-72 -58,-30 Z" fill="url(#${id}-hairG)"/>` },
      bun: { back: `<circle cx="0" cy="-118" r="34" fill="url(#${id}-hairG)"/>`, front: `<path d="M -56,-20 C -64,-94 -28,-114 2,-112 C 34,-112 64,-94 56,-20 C 50,-70 30,-86 0,-86 C -28,-86 -50,-70 -56,-20 Z" fill="url(#${id}-hairG)"/>` },
    }[L.style];
    const eye = (s) => `<g data-r="eye${s}" transform="translate(${s === 'L' ? -22 : 22},-10)">
        <clipPath id="${id}-ec${s}"><path data-r="ecp${s}" d="M -15,0 C -10,-9 10,-9 15,0 C 10,7 -10,7 -15,0 Z"/></clipPath>
        <path data-r="ew${s}" d="M -15,0 C -10,-9 10,-9 15,0 C 10,7 -10,7 -15,0 Z" fill="#F7F3EE"/>
        <g clip-path="url(#${id}-ec${s})"><g data-r="iris${s}"><circle r="7.5" fill="${L.eye}"/><circle r="7.5" fill="none" stroke="rgba(0,0,0,.35)" stroke-width="1.5"/><circle r="3.6" fill="#0A0A0A"/><circle cx="2.5" cy="-2.5" r="1.8" fill="#fff"/></g>
          <rect data-r="lid${s}" x="-18" y="-12" width="36" height="0" fill="${L.skin}"/></g>
        <path data-r="lash${s}" d="M -15,0 C -10,-9 10,-9 15,0" fill="none" stroke="${f ? '#140a08' : 'rgba(40,20,10,.75)'}" stroke-width="${f ? 2.8 : 1.8}" stroke-linecap="round"/>
        ${f ? `<path d="M ${s === 'L' ? '-15,0 l -5,-4' : '15,0 l 5,-4'}" stroke="#140a08" stroke-width="2.5" stroke-linecap="round"/>` : ''}
      </g>`;
    const brow = (s) => `<path data-r="brow${s}" d="" fill="${L.brow}"/>`;
    const sk = L.skin;
    return `<defs>
      <radialGradient id="${id}-skinG" cx="40%" cy="35%" r="75%"><stop offset="0" stop-color="${sk}"/><stop offset="1" stop-color="${L.skinSh}"/></radialGradient>
      <linearGradient id="${id}-hairG" x1="0" y1="0" x2="0.3" y2="1"><stop offset="0" stop-color="${L.hairHi}"/><stop offset=".5" stop-color="${L.hair}"/><stop offset="1" stop-color="${L.hair}"/></linearGradient>
      ${L.suit ? `<linearGradient id="${id}-suitG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${L.suitHi}"/><stop offset=".6" stop-color="${L.suit}"/><stop offset="1" stop-color="#05060a"/></linearGradient>` : ''}
      ${L.dress ? `<linearGradient id="${id}-dressG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${L.dressHi}"/><stop offset=".55" stop-color="${L.dress}"/><stop offset="1" stop-color="#03261c"/></linearGradient>` : ''}
      <radialGradient id="${id}-glowG"><stop offset="0" stop-color="#9fd0ff" stop-opacity=".55"/><stop offset="1" stop-color="#9fd0ff" stop-opacity="0"/></radialGradient>
    </defs>
    <g data-r="root">
     <g data-r="legs"><path data-r="legL" fill="${L.dress || '#14182a'}"/><path data-r="legR" fill="${L.dress || '#14182a'}"/>
       <ellipse data-r="shoeL" rx="26" ry="10" fill="#0b0b0b"/><ellipse data-r="shoeR" rx="26" ry="10" fill="#0b0b0b"/></g>
     <g data-r="body">
      ${hair.back ? `<g data-r="hairBackWrap"><g transform="translate(0,-345)">${hair.back}</g></g>` : ''}
      <ellipse cx="0" cy="-10" rx="${sh - 8}" ry="16" fill="rgba(0,0,0,.25)"/>
      <rect x="-19" y="-298" width="38" height="66" rx="12" fill="url(#${id}-skinG)"/>
      <path d="M -19,-280 C -8,-268 8,-268 19,-280 L 19,-266 C 8,-258 -8,-258 -19,-266 Z" fill="rgba(0,0,0,.12)"/>
      <g data-r="torso">${torso}
        ${f && L.necklace ? `<path d="M -26,-232 C -16,-196 16,-196 26,-232" stroke="#F3D27A" stroke-width="2.5" fill="none"/><circle cx="0" cy="-202" r="5" fill="#fff" stroke="#F3D27A" stroke-width="2"/>` : ''}
      </g>
      <g data-r="head">
        <ellipse data-r="earL" cx="-55" cy="-351" rx="9" ry="17" fill="${L.skinSh}"/><ellipse data-r="earR" cx="55" cy="-351" rx="9" ry="17" fill="${L.skinSh}"/>
        ${f && L.earrings ? `<g data-r="earrL"><circle cx="-56" cy="-328" r="5" fill="#F3D27A"/><path d="M -56,-326 L -56,-306" stroke="#F3D27A" stroke-width="2"/><circle cx="-56" cy="-302" r="5" fill="#F3D27A"/></g><g data-r="earrR"><circle cx="56" cy="-328" r="5" fill="#F3D27A"/><path d="M 56,-326 L 56,-306" stroke="#F3D27A" stroke-width="2"/><circle cx="56" cy="-302" r="5" fill="#F3D27A"/></g>` : ''}
        <g transform="translate(0,-345)">
          <path data-r="face" d="${jaw}" fill="url(#${id}-skinG)"/>
          <path d="${jaw}" fill="none" stroke="rgba(80,30,10,.18)" stroke-width="2"/>
          ${L.stubble ? `<path data-r="stub" d="M -54,-6 C -50,30 -30,66 0,74 C 30,66 50,30 54,-6 C 44,20 30,30 18,28 C 8,26 -8,26 -18,28 C -30,30 -44,20 -54,-6 Z" fill="#2a1a12" opacity="${L.stubble}"/>` : ''}
          <ellipse cx="-30" cy="18" rx="12" ry="7" fill="#ff6b6b" opacity="${f ? .28 : .1}"/><ellipse cx="30" cy="18" rx="12" ry="7" fill="#ff6b6b" opacity="${f ? .28 : .1}"/>
          <g data-r="feat">
            ${f ? `<path d="M -36,-12 C -30,-22 -14,-22 -8,-12 M 8,-12 C 14,-22 30,-22 36,-12" stroke="#8a4a5a" stroke-width="6" opacity=".25" fill="none"/>` : ''}
            ${eye('L')}${eye('R')}${brow('L')}${brow('R')}
            <path data-r="nose" d="M -2,-4 C -3,8 -9,20 -8,25 C -4,30 4,30 8,25" fill="none" stroke="${L.skinSh}" stroke-width="3" stroke-linecap="round"/>
            <ellipse cx="-5" cy="26" rx="3" ry="2" fill="rgba(60,20,10,.45)"/><ellipse cx="5" cy="26" rx="3" ry="2" fill="rgba(60,20,10,.45)"/>
            <g data-r="mouth" transform="translate(0,44)">
              <clipPath id="${id}-mc"><path data-r="mclip"/></clipPath>
              <path data-r="lips" fill="${L.lip}"/>
              <path data-r="inner" fill="#3a0e12"/>
              <g clip-path="url(#${id}-mc)"><rect data-r="teeth" fill="#fbf7f0"/><ellipse data-r="tongue" fill="#c04a5c"/></g>
              <path data-r="lline" fill="none" stroke="#5a2018" stroke-width="2.4" stroke-linecap="round"/>
            </g>
          </g>
          <ellipse data-r="glow" cx="0" cy="10" rx="80" ry="90" fill="url(#${id}-glowG)" opacity="0"/>
          <g data-r="hairF">${hair.front}</g>
        </g>
      </g>
      ${this.noArms ? '' : this.armSVG('L') + this.armSVG('R')}
     </g>
    </g>`;
  }
  armSVG(s) {
    const L = this.L, f = L.gender === 'f', c = f ? this.L.skin : L.suit, w = f ? 26 : 42;
    const watch = (L.watch && s === 'R') ? `<g data-r="watch${s}"><rect x="-14" y="-6" width="28" height="12" rx="4" fill="${L.watch === 'gold' ? '#C9A13B' : '#B8BEC9'}"/><circle r="10" fill="${L.watch === 'gold' ? '#E9C25A' : '#DDE2EA'}"/><circle r="7.5" fill="${L.watch === 'gold' ? '#1a1a1a' : '#1D4E89'}"/><path d="M0,0 L0,-5 M0,0 L4,1" stroke="#fff" stroke-width="1.2"/></g>` : '';
    const bracelet = f && s === 'L' ? `<g data-r="brace${s}"><rect x="-12" y="-4" width="24" height="7" rx="3" fill="#F3D27A"/></g>` : '';
    return `<g data-r="arm${s}">
      <path data-r="ua${s}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round"/>
      <path data-r="fa${s}" fill="none" stroke="${c}" stroke-width="${w - 6}" stroke-linecap="round"/>
      ${!f ? `<path data-r="cuff${s}" fill="none" stroke="${L.shirt === '#121212' ? '#222' : '#F4F5F7'}" stroke-width="${w - 10}" stroke-linecap="butt"/>` : ''}
      <g data-r="hand${s}"><ellipse rx="17" ry="20" fill="url(#${this.id}-skinG)"/><ellipse cx="${s === 'L' ? 13 : -13}" cy="-4" rx="6" ry="12" fill="${L.skin}" transform="rotate(${s === 'L' ? -30 : 30})"/>
        <path d="M -9,12 L -9,20 M -3,13 L -3,22 M 3,13 L 3,22 M 9,12 L 9,20" stroke="${L.skinSh}" stroke-width="2" stroke-linecap="round"/></g>
      ${watch}${bracelet}<g data-r="prop${s}"></g>
    </g>`;
  }
  ik(S, H, a, b, side) {
    { const d0 = Math.hypot(H.x - S.x, H.y - S.y), k = clamp((d0 + 40) / (a + b), .55, 1); a *= k; b *= k; }
    let dx = H.x - S.x, dy = H.y - S.y, d = Math.hypot(dx, dy); d = Math.min(d, a + b - 1); d = Math.max(d, Math.abs(a - b) + 1);
    const ang = Math.atan2(dy, dx), cosA = (a * a + d * d - b * b) / (2 * a * d), A = Math.acos(clamp(cosA, -1, 1));
    const e = ang + side * A; const E = { x: S.x + Math.cos(e) * a, y: S.y + Math.sin(e) * a };
    const hx = S.x + Math.cos(ang) * d, hy = S.y + Math.sin(ang) * d; return { E, H: { x: hx, y: hy } };
  }
  mouthPaths(m, smile) {
    const W = lerp(30, 46, m.w) * (1 - .35 * m.r), H = m.o * 26 * (1 + .25 * m.r), cy = -smile * 5, c = m.c || 0;
    const up = -H / 2 - 5 - c * 1.5, dn = H / 2 + 8 + c * 1.5;
    const outer = `M ${-W / 2},${cy} C ${-W / 4},${up - 1} ${-6},${up - 2} 0,${up + 1} C 6,${up - 2} ${W / 4},${up - 1} ${W / 2},${cy} C ${W / 3},${dn + smile * 2} ${-W / 3},${dn + smile * 2} ${-W / 2},${cy} Z`;
    const ih = Math.max(0, H);
    const inner = ih > 1.2 ? `M ${-W / 2 + 3},${cy} C ${-W / 4},${-ih / 2 + 1} ${W / 4},${-ih / 2 + 1} ${W / 2 - 3},${cy} C ${W / 4},${ih / 2 + smile * 2} ${-W / 4},${ih / 2 + smile * 2} ${-W / 2 + 3},${cy} Z` : 'M0,0';
    const line = `M ${-W / 2},${cy} C ${-W / 4},${cy + 2.5 + smile * 3} ${W / 4},${cy + 2.5 + smile * 3} ${W / 2},${cy}`;
    return { outer, inner, line, W, H: ih, cy };
  }
  browPath(s, raise, furrow, angry) {
    const sg = s === 'L' ? -1 : 1, y0 = -30 - raise * 9;
    const inY = y0 + furrow * 6 - raise * 3, outY = y0 - furrow * 2 + (angry || 0) * -3;
    const ix = 8 * sg, ox = 36 * sg, th = this.L.gender === 'f' ? 4 : 6.5;
    return `M ${ix},${inY} C ${(ix + ox) / 2},${(inY + outY) / 2 - 7} ${ox - 6 * sg},${outY - 4} ${ox},${outY + 2} C ${ox - 8 * sg},${outY - 1 + th * .4} ${(ix + ox) / 2},${(inY + outY) / 2 - 7 + th} ${ix},${inY + th} Z`;
  }
  update(s) {
    const r = this.r, L = this.L, f = L.gender === 'f';
    this.g.style.display = s.hidden ? 'none' : ''; if (this.ga) this.ga.style.display = s.hidden ? 'none' : '';
    if (s.hidden) return;
    const stand = s.stand || 0, bob = s.walk ? Math.abs(Math.sin(s.walkPh)) * 7 : 0;
    const hipY = s.y - stand * 150 - bob * s.scale;
    r.root.setAttribute('transform', `translate(${s.x},${hipY}) scale(${s.scale})`);
    if (r.aroot) r.aroot.setAttribute('transform', `translate(${s.x},${hipY}) scale(${s.scale})`);
    // legs (visible only when standing)
    r.legs.style.display = stand > .2 ? '' : 'none';
    if (stand > .2) {
      const ph = s.walk ? s.walkPh : 0, sw = s.walk ? Math.sin(ph) * 22 : 0;
      const leg = (side, a) => { const hx = side * 26, kx = hx + Math.sin(a * Math.PI / 180) * 150, ky = 160, fx = hx + Math.sin(a * Math.PI / 180) * 300, fy = 320 - (s.walk ? Math.max(0, Math.sin(ph * (side > 0 ? 1 : -1))) * 14 : 0);
        return { d: f ? `M ${hx - 30},-10 L ${hx + 30},-10 L ${fx + 18},${fy} L ${fx - 18},${fy} Z` : `M ${hx - 24},-6 L ${hx + 24},-6 L ${kx + 21},${ky} L ${fx + 18},${fy} L ${fx - 18},${fy} L ${kx - 21},${ky} Z`, fx, fy }; };
      const a = leg(-1, sw), b = leg(1, -sw);
      r.legL.setAttribute('d', a.d); r.legR.setAttribute('d', b.d);
      r.shoeL.setAttribute('cx', a.fx - 4); r.shoeL.setAttribute('cy', a.fy + 4); r.shoeR.setAttribute('cx', b.fx + 4); r.shoeR.setAttribute('cy', b.fy + 4);
      if (f) { r.legL.setAttribute('d', `M -64,-10 L 64,-10 L ${86 + sw},320 L ${-86 + sw},320 Z`); r.legR.setAttribute('d', 'M0,0'); }
    }
    const breath = Math.sin(s.t * 1.6 + this.id.length) * .006;
    r.body.setAttribute('transform', `translate(0,0) rotate(${s.lean || 0},0,0) scale(1,${1 + breath})`);
    if (r.abody) r.abody.setAttribute('transform', `rotate(${s.lean || 0},0,0) scale(1,${1 + breath})`);
    // head
    const turn = clamp(s.turn ?? s.lookX * .55, -1, 1);
    r.head.setAttribute('transform', `translate(${turn * 4},${(s.nod || 0)}) rotate(${s.tilt || 0},0,-290)`);
    r.feat.setAttribute('transform', `translate(${turn * 11},${(s.lookY || 0) * 2})`);
    r.hairF.setAttribute('transform', `translate(${turn * 4},0)`);
    if (r.hairBackWrap) r.hairBackWrap.setAttribute('transform', `translate(${-turn * 4},0) rotate(${(s.tilt || 0) * .5},0,-290)`);
    r.earL.setAttribute('rx', 9 * (1 + turn * .35)); r.earR.setAttribute('rx', 9 * (1 - turn * .35));
    r.earL.setAttribute('cx', -55 + turn * 4); r.earR.setAttribute('cx', 55 + turn * 4);
    // eyes
    const wide = s.wide || 0, sq = s.squint || 0;
    for (const sd of ['L', 'R']) {
      const eh = 9 * (1 + wide * .45) * (1 - sq * .35), lo = 7 * (1 + wide * .3);
      const d = `M -15,0 C -10,${-eh} 10,${-eh} 15,0 C 10,${lo} -10,${lo} -15,0 Z`;
      r['ew' + sd].setAttribute('d', d); r['ecp' + sd].setAttribute('d', d);
      r['lash' + sd].setAttribute('d', `M -15,0 C -10,${-eh} 10,${-eh} 15,0`);
      r['iris' + sd].setAttribute('transform', `translate(${clamp(s.lookX, -1, 1) * 6},${(s.lookY || 0) * 3 - .5})`);
      const bl = clamp(s.blink || 0), lidH = (eh + lo + 4) * bl;
      r['lid' + sd].setAttribute('y', -eh - 3); r['lid' + sd].setAttribute('height', lidH);
      r['lash' + sd].setAttribute('transform', `translate(0,${bl * (eh + lo) * .9})`);
      r['brow' + sd].setAttribute('d', this.browPath(sd, (s.brow || 0) + wide * .8 + (sd === 'R' ? (s.browR || 0) : 0), s.furrow || 0, s.angry));
    }
    // mouth
    let m = s.mouth || REST; const jaw = s.jaw || 0;
    m = { o: clamp(m.o + jaw * .9, 0, 1.2), w: lerp(m.w, .3, jaw * .6), r: lerp(m.r, .5, jaw * .5), c: m.c || 0, f: m.f || 0 };
    const smile = s.smile || 0;
    const mp = this.mouthPaths(m, smile);
    r.lips.setAttribute('d', mp.outer); r.inner.setAttribute('d', mp.inner); r.mclip.setAttribute('d', mp.inner);
    r.lline.setAttribute('d', mp.line); r.lline.style.opacity = mp.H < 2 ? 1 : 0;
    r.teeth.setAttribute('x', -mp.W / 2); r.teeth.setAttribute('y', mp.cy - mp.H / 2 - 1); r.teeth.setAttribute('width', mp.W); r.teeth.setAttribute('height', Math.min(mp.H * .38, 7) + (m.f ? 3 : 0));
    r.tongue.setAttribute('cx', 0); r.tongue.setAttribute('cy', mp.cy + mp.H / 2); r.tongue.setAttribute('rx', mp.W / 3.5); r.tongue.setAttribute('ry', mp.H / 3);
    r.glow.setAttribute('opacity', s.glow || 0);
    // arms
    const shY = -215, shX = f ? 72 : 100;
    for (const sd of ['L', 'R']) {
      const sg = sd === 'L' ? -1 : 1, S = { x: sg * shX, y: shY }, Ht = sd === 'L' ? s.handL : s.handR;
      const { E, H } = this.ik(S, Ht, f ? 112 : 120, f ? 104 : 112, sg > 0 ? -1 : 1);
      r['ua' + sd].setAttribute('d', `M ${S.x},${S.y} L ${E.x},${E.y}`);
      r['fa' + sd].setAttribute('d', `M ${E.x},${E.y} L ${H.x},${H.y}`);
      const ang = Math.atan2(H.y - E.y, H.x - E.x) * 180 / Math.PI;
      const wx = lerp(E.x, H.x, .82), wy = lerp(E.y, H.y, .82);
      if (r['cuff' + sd]) r['cuff' + sd].setAttribute('d', `M ${lerp(E.x, H.x, .9)},${lerp(E.y, H.y, .9)} L ${lerp(E.x, H.x, .97)},${lerp(E.y, H.y, .97)}`);
      const hx = H.x + Math.cos(ang * Math.PI / 180) * 16, hy = H.y + Math.sin(ang * Math.PI / 180) * 16;
      r['hand' + sd].setAttribute('transform', `translate(${hx},${hy}) rotate(${ang - 90 + (s['handRot' + sd] || 0)})`);
      if (r['watch' + sd]) r['watch' + sd].setAttribute('transform', `translate(${wx},${wy}) rotate(${ang - 90})`);
      if (r['brace' + sd]) r['brace' + sd].setAttribute('transform', `translate(${wx},${wy}) rotate(${ang - 90})`);
      r['prop' + sd].setAttribute('transform', `translate(${hx},${hy})`);
    }
  }
}
