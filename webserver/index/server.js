import Fastify from 'fastify';
import fs from 'fs/promises';
import path from 'path';
import { load as loadHTML } from 'cheerio';

const WEBROOT = '/mnt/webroot';
const app = Fastify({ logger: false });

const DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit'
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => {
    switch (ch) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return ch;
    }
  });
}

function formatBytes(bytes) {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB', 'PB'];
  let size = bytes;
  let unit = 'B';
  for (const next of units) {
    const value = size / 1024;
    if (value < 1) break;
    size = value;
    unit = next;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
}

function formatDate(date) {
  if (!date) return '—';
  return DATE_FORMATTER.format(date);
}

function buildHref(parts, { trailingSlash = false } = {}) {
  const encoded = parts.map(part => encodeURIComponent(part)).join('/');
  if (!encoded) {
    const target = trailingSlash ? '/files' : '/';
    return target;
  }
  const base = `/${encoded}`;
  return trailingSlash ? `${base}/` : base;
}

function describeType(item) {
  if (item.type === 'dir') return 'Folder';
  if (!item.ext) return 'File';
  const label = item.ext.replace('.', '').toUpperCase();
  return label || 'File';
}

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
  const visible = entries.filter(e => !e.name.startsWith('.'));
  const items = await Promise.all(
    visible.map(async e => {
      const full = path.join(dir, e.name);
      const stat = await fs.stat(full);
      if (e.isDirectory()) {
        return {
          type: 'dir',
          name: e.name,
          mtime: stat.mtime
        };
      }
      const ext = path.extname(e.name).toLowerCase();
      let title = e.name;
      if (ext === '.html' || ext === '.htm') {
        title = await inferTitle(full, e.name);
      }
      return {
        type: 'file',
        name: e.name,
        title,
        ext,
        size: stat.size,
        mtime: stat.mtime
      };
    })
  );

  items.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
    const labelA = (a.title || a.name);
    const labelB = (b.title || b.name);
    return labelA.localeCompare(labelB, undefined, { sensitivity: 'base' });
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
  const relative = path.relative(WEBROOT, dir);
  const segments = relative ? relative.split(path.sep).filter(Boolean) : [];
  const displayPath = segments.length ? `/${segments.join('/')}/` : '/';

  const breadcrumbParts = ['<a href="/files">All Files</a>'];
  segments.forEach((seg, idx) => {
    breadcrumbParts.push('<span class="crumb-sep">/</span>');
    const href = buildHref(segments.slice(0, idx + 1), { trailingSlash: true });
    breadcrumbParts.push(`<a href="${href}">${escapeHtml(seg)}</a>`);
  });

  const parentHref = segments.length === 0
    ? null
    : (segments.length === 1 ? '/files' : buildHref(segments.slice(0, -1), { trailingSlash: true }));

  const parentRow = parentHref ? `<tr class="row-parent">
      <td class="cell-name" data-label="Name">
        <a class="entry" href="${parentHref}" aria-label="Go up to the parent directory">
          <span class="icon icon-up" data-icon="↩" aria-hidden="true"></span>
          <span class="name-text">.. <span class="muted">(Parent)</span></span>
        </a>
      </td>
      <td class="cell-type" data-label="Type"><span class="badge badge-dir">Folder</span></td>
      <td class="cell-size" data-label="Size">—</td>
      <td class="cell-date" data-label="Modified">—</td>
    </tr>` : '';

  const entryRows = items.map(it => {
    const href = buildHref([...segments, it.name], { trailingSlash: it.type === 'dir' });
    const iconClass = it.type === 'dir' ? 'icon-dir' : 'icon-file';
    const iconSymbol = it.type === 'dir' ? '📁' : '📄';
    const safeName = escapeHtml(it.name);
    const label = it.type === 'file' && it.title && it.title !== it.name
      ? `${escapeHtml(it.title)} <span class="muted">(${safeName})</span>`
      : `${safeName}${it.type === 'dir' ? '/' : ''}`;
    const typeLabel = escapeHtml(describeType(it));
    const sizeLabel = it.type === 'dir' ? '—' : formatBytes(it.size);
    const modifiedLabel = formatDate(it.mtime);
    const badgeClass = it.type === 'dir' ? 'badge-dir' : 'badge-file';
    return `<tr>
      <td class="cell-name" data-label="Name">
        <a class="entry" href="${href}">
          <span class="icon ${iconClass}" data-icon="${iconSymbol}" aria-hidden="true"></span>
          <span class="name-text">${label}</span>
        </a>
      </td>
      <td class="cell-type" data-label="Type"><span class="badge ${badgeClass}">${typeLabel}</span></td>
      <td class="cell-size" data-label="Size">${sizeLabel}</td>
      <td class="cell-date" data-label="Modified">${modifiedLabel}</td>
    </tr>`;
  }).join('');

  let bodyHtml = parentRow;
  if (entryRows) {
    bodyHtml += entryRows;
  } else {
    bodyHtml += `<tr class="empty">
      <td colspan="4">
        <div class="empty-state">
          <strong>This folder is empty.</strong>
          <p class="muted">Add files under <code>${escapeHtml(displayPath)}</code> to see them listed here.</p>
        </div>
      </td>
    </tr>`;
  }

  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Files · ${escapeHtml(displayPath)}</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #eef2ff;
      --surface: rgba(255,255,255,0.93);
      --text: #0f172a;
      --text-strong: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --border: rgba(15,23,42,0.08);
      --table-bg: rgba(255,255,255,0.75);
      --table-head: rgba(15,23,42,0.04);
      --row-border: rgba(15,23,42,0.06);
      --row-hover: rgba(37,99,235,0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --surface: rgba(15,23,42,0.92);
        --text: #e2e8f0;
        --text-strong: #f8fafc;
        --muted: #94a3b8;
        --accent: #60a5fa;
        --border: rgba(148,163,184,0.25);
        --table-bg: rgba(15,23,42,0.85);
        --table-head: rgba(148,163,184,0.12);
        --row-border: rgba(148,163,184,0.14);
        --row-hover: rgba(96,165,250,0.14);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
      color: var(--text);
      background:
        radial-gradient(1200px 600px at -10% -10%, rgba(37,99,235,0.15), transparent 55%),
        radial-gradient(1200px 600px at 110% 110%, rgba(16,185,129,0.13), transparent 60%),
        var(--bg);
      min-height: 100vh;
    }
    code { font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    .page {
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 56px 16px;
    }
    .card {
      width: 100%;
      max-width: 980px;
      background: var(--surface);
      border-radius: 22px;
      padding: 32px 36px;
      border: 1px solid var(--border);
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.16);
      backdrop-filter: blur(12px);
    }
    .card__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.32em;
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--muted);
    }
    h1 {
      margin: 8px 0 4px;
      font-size: clamp(1.75rem, 3vw, 2.2rem);
      color: var(--text-strong);
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .ghost-link {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 10px 18px;
      font-size: 0.9rem;
      font-weight: 600;
      text-decoration: none;
      color: var(--accent);
      background: rgba(37,99,235,0.08);
      transition: all 0.18s ease;
    }
    .ghost-link:hover {
      border-color: rgba(37,99,235,0.4);
      background: rgba(37,99,235,0.12);
    }
    .breadcrumbs {
      margin-top: 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .breadcrumbs a {
      color: inherit;
      text-decoration: none;
      padding-bottom: 2px;
      border-bottom: 1px solid transparent;
    }
    .breadcrumbs a:hover {
      color: var(--text-strong);
      border-color: currentColor;
    }
    .crumb-sep {
      opacity: 0.6;
    }
    .table-wrap {
      margin-top: 28px;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: var(--table-bg);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 540px;
    }
    thead th {
      text-align: left;
      padding: 16px 22px;
      font-size: 0.75rem;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--muted);
      background: var(--table-head);
    }
    tbody td {
      padding: 18px 22px;
      border-top: 1px solid var(--row-border);
      vertical-align: middle;
      font-size: 0.95rem;
    }
    tbody tr:hover {
      background: var(--row-hover);
    }
    .entry {
      display: flex;
      align-items: center;
      gap: 12px;
      color: var(--text-strong);
      font-weight: 600;
      text-decoration: none;
    }
    .entry:hover {
      color: var(--accent);
    }
    .name-text .muted {
      font-weight: 500;
    }
    .icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 12px;
      font-size: 1rem;
      background: rgba(37,99,235,0.12);
      color: #1d4ed8;
    }
    .icon-file {
      background: rgba(16,185,129,0.12);
      color: #047857;
    }
    .icon-up {
      background: rgba(234,179,8,0.16);
      color: #b45309;
    }
    .icon::before {
      content: attr(data-icon);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 4px 12px;
      font-size: 0.75rem;
      font-weight: 600;
      border-radius: 999px;
      background: rgba(37,99,235,0.10);
      color: #1d4ed8;
    }
    .badge-file {
      background: rgba(16,185,129,0.12);
      color: #047857;
    }
    .empty {
      text-align: center;
    }
    .empty-state {
      padding: 36px 18px;
    }
    .empty-state p {
      margin: 8px 0 0;
      font-size: 0.9rem;
    }
    @media (max-width: 720px) {
      .card {
        padding: 28px 20px;
        border-radius: 18px;
      }
      .table-wrap {
        border: none;
        background: transparent;
      }
      table, thead, tbody, tr, td, th {
        display: block;
        width: 100%;
      }
      thead {
        display: none;
      }
      tbody tr {
        border: 1px solid var(--border);
        border-radius: 14px;
        margin-bottom: 14px;
        padding: 14px;
        background: var(--table-bg);
      }
      tbody td {
        border: none;
        padding: 8px 0;
      }
      tbody td::before {
        content: attr(data-label);
        display: block;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 4px;
      }
      .icon {
        width: 32px;
        height: 32px;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <main class="card" aria-label="Directory listing">
      <header class="card__header">
        <div>
          <div class="eyebrow">Local Webroot</div>
          <h1>File Browser</h1>
          <p class="subtitle">Serving <code>${escapeHtml(displayPath)}</code></p>
        </div>
        <a class="ghost-link" href="/" title="Open the root site">View Site</a>
      </header>
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        ${breadcrumbParts.join(' ')}
      </nav>
      <div class="table-wrap" role="region" aria-live="polite">
        <table role="grid">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Type</th>
              <th scope="col">Size</th>
              <th scope="col">Modified</th>
            </tr>
          </thead>
          <tbody>
            ${bodyHtml}
          </tbody>
        </table>
      </div>
    </main>
  </div>
</body>
</html>`;

  reply.type('text/html; charset=utf-8').send(html);
});

app.listen({ port: 3000, host: '0.0.0.0' });
