import Fastify from 'fastify';
import fs from 'fs/promises';
import path from 'path';
import { load as loadHTML } from 'cheerio';

const WEBROOT = '/mnt/webroot';
const app = Fastify({ logger: false });

// Utility: get title from an HTML file (fallback to filename)
async function inferTitle(filePath, fileName) {
  try {
    const data = await fs.readFile(filePath, 'utf8');
    const $ = loadHTML(data);
    const t = $('title').first().text().trim();
    return t || fileName;
  } catch {
    return fileName;
  }
}

async function scanDir(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const items = [];
  for (const e of entries) {
    if (e.name.startsWith('.')) continue; // hide dotfiles
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      items.push({ type: 'dir', name: e.name, href: `/${e.name}/` });
    } else {
      const ext = path.extname(e.name).toLowerCase();
      const rel = '/' + path.relative(WEBROOT, full).split(path.sep).join('/');
      let title = e.name;
      if (ext === '.html' || ext === '.htm') {
        title = await inferTitle(full, e.name);
      }
      items.push({ type: 'file', name: e.name, title, href: rel, ext });
    }
  }
  // Simple ordering: dirs first, then files by title
  items.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
    return (a.title || a.name).localeCompare(b.title || b.name);
  });
  return items;
}

app.get('/*', async (req, reply) => {
  // Resolve requested subdirectory relative to WEBROOT
  const reqPath = decodeURIComponent(req.params['*'] || '');
  const fsPath = path.join(WEBROOT, reqPath);
  let stat;
  try { stat = await fs.stat(fsPath); } catch { /* ignore */ }
  const dir = stat && stat.isDirectory() ? fsPath : WEBROOT;

  const items = await scanDir(dir);
  const relPrefix = dir === WEBROOT ? '' : '/' + path.relative(WEBROOT, dir).split(path.sep).join('/') + '/';
  const breadcrumbs = relPrefix.split('/').filter(Boolean);

  const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Dynamic Index</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; margin: 2rem; }
    header { display:flex; gap:.5rem; align-items:center; margin-bottom:1rem; }
    ul { list-style:none; padding:0; margin:0; }
    li { padding:.35rem 0; }
    .dir { font-weight:600; }
    .muted { color:#666; font-size:.9em; }
    a { text-decoration:none; }
    a:hover { text-decoration:underline; }
  </style>
</head>
<body>
  <header>
    <div><strong>Index</strong> on <code>${relPrefix || '/'}</code></div>
  </header>
  ${breadcrumbs.length ? `<div class="muted">/ ${
    breadcrumbs.map((b, i) => {
      const href = '/' + breadcrumbs.slice(0, i + 1).join('/') + '/';
      return `<a href="${href}">${b}</a>`;
    }).join(' / ')
  }</div>` : ''}

  <ul>
    ${dir !== WEBROOT ? `<li class="dir"><a href="${relPrefix.split('/').slice(0,-2).join('/') || '/'}">..</a></li>` : ''}
    ${items.map(it => {
      if (it.type === 'dir') {
        const href = (relPrefix + it.name + '/').replace('//','/');
        return `<li class="dir">📁 <a href="${href}">${it.name}/</a></li>`;
      } else {
        const href = (relPrefix + it.name).replace('//','/');
        const label = it.title !== it.name ? `${it.title} <span class="muted">(${it.name})</span>` : it.name;
        return `<li>📄 <a href="${href}">${label}</a></li>`;
      }
    }).join('')}
  </ul>
</body>
</html>`;

  reply.type('text/html').send(html);
});

app.listen({ port: 3000, host: '0.0.0.0' });
