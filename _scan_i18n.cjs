// i18n 保留字符扫描（vue-i18n message 值）：裸 @ / 裸 | / 未配对 {} / en 里的 CJK
// zh.js/en.js 会展开 ./views/* 片段（同文件 zh/en）。
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, 'frontend', 'src', 'locales');
const vdir = path.join(dir, 'views');
const tmp = (n) => path.join(__dirname, `_scan_tmp_${n}.cjs`);

// views 片段 → 临时 CJS
const frags = {};
let i = 0;
for (const f of fs.readdirSync(vdir).filter(f => f.endsWith('.js'))) {
  const raw = fs.readFileSync(path.join(vdir, f), 'utf8');
  const p = tmp(i++);
  fs.writeFileSync(p, raw.replace(/export\s+default/, 'module.exports ='));
  frags[f.replace(/\.js$/, '')] = { path: p, exp: require(p) };
}

function walk(obj, prefix, out) {
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === 'string') out.push([key, v]);
    else if (v && typeof v === 'object') walk(v, key, out);
  }
}

let problems = 0;
const results = {};
for (const f of ['zh.js', 'en.js']) {
  let raw = fs.readFileSync(path.join(dir, f), 'utf8');
  // 扫描副本容错：修复 f48bbd7 引入的两类语法错误（缺逗号 + 单引号串里的 {'@'}）
  raw = raw.replace(/platformKey: '([^']*)'(\r?\n)/, "platformKey: '$1',$2");
  raw = raw.split("dev{'@'}{domain}").join('dev{"@"}{domain}');
  const converted = raw.replace(
    /import\s+(\w+)\s+from\s+'\.\/views\/(\w+)'/g,
    (m, name, frag) => `const ${name} = ${JSON.stringify(frags[frag].exp)}`
  ).replace(/export\s+default/, 'module.exports =');
  const p = tmp(i++);
  fs.writeFileSync(p, converted);
  let obj; try { obj = require(p); } finally { fs.unlinkSync(p); }
  const pairs = [];
  walk(obj, '', pairs);
  results[f] = pairs.map(([k]) => k);
  const issues = [];
  for (const [key, val] of pairs) {
    const noEsc = val.replace(/\{\s*['"][@|{}]['"]\s*\}/g, ''); // {'@'} 字面量转义剔除
    if (noEsc.includes('@')) issues.push(`[AT   ] ${key}: ${JSON.stringify(val)}`);
    if (noEsc.includes('|')) issues.push(`[PIPE ] ${key}: ${JSON.stringify(val)}`);
    const stripped = noEsc.replace(/\{[^{}]*\}/g, '');
    if (stripped.includes('{') || stripped.includes('}')) issues.push(`[BRACE] ${key}: ${JSON.stringify(val)}`);
  }
  const cjk = [];
  if (f === 'en.js') for (const [key, val] of pairs) if (/[一-鿿]/.test(val)) cjk.push(`[CJK  ] ${key}: ${JSON.stringify(val)}`);
  console.log(`=== ${f}: ${pairs.length} 条 message | ${issues.length} 保留字符问题 | ${cjk.length} CJK ===`);
  for (const x of issues) { console.log(x); problems++; }
  for (const x of cjk) { console.log(x); problems++; }
}
for (const k in frags) fs.unlinkSync(frags[k].path);
// zh/en 键路径差集
if (results['zh.js'] && results['en.js']) {
  const zs = new Set(results['zh.js']), es = new Set(results['en.js']);
  const oz = [...zs].filter(k => !es.has(k)), oe = [...es].filter(k => !zs.has(k));
  console.log(`\nzh-only keys: ${oz.length}`, oz.slice(0, 30));
  console.log(`en-only keys: ${oe.length}`, oe.slice(0, 30));
  if (oz.length || oe.length) problems += oz.length + oe.length;
}
console.log(`\nTOTAL problems: ${problems}`);
