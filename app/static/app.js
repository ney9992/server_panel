const $ = (id) => document.getElementById(id);
let kind = 'movies';
let page = 'media';
let state = {libraries: {}, torrents: [], torrentError: '', disk: {used: 0, total: 1}};
let uploads = [];
let timer = null;
let toastTimer;

function errorMessage(e) { return e instanceof Error ? e.message : String(e); }
function toast(msg) {
  const el = $('toast'); el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}
function byteSize(b) {
  if (!b) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']; let i = 0;
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
async function api(url, options = {}) {
  const response = await fetch(url, {...options, credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    if (response.status === 401 && url !== '/api/login') showLogin();
    throw new Error(payload.detail || `Ошибка ${response.status}`);
  }
  return payload;
}
function showLogin() {
  $('dashboard').hidden = true; $('login').hidden = false;
  clearInterval(timer); timer = null;
}
function showDashboard() {
  $('login').hidden = true; $('dashboard').hidden = false;
  if (!timer) timer = setInterval(refresh, 5000);
  refresh();
}
$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault(); $('login-error').textContent = '';
  try {
    await api('/api/login', {method: 'POST', body: JSON.stringify({user: $('user').value, password: $('password').value})});
    $('password').value = ''; showDashboard();
  } catch (e) { $('login-error').textContent = errorMessage(e); }
});
$('logout').addEventListener('click', async () => {
  try { await api('/api/logout', {method: 'POST'}); } catch (_) {}
  showLogin();
});
for (const b of document.querySelectorAll('[data-page]')) {
  b.addEventListener('click', () => {
    page = b.dataset.page;
    document.querySelectorAll('[data-page]').forEach(n => n.classList.toggle('active', n === b));
    $('media-page').hidden = page !== 'media'; $('downloads-page').hidden = page !== 'downloads';
  });
}
for (const b of document.querySelectorAll('[data-kind]')) {
  b.addEventListener('click', () => {
    kind = b.dataset.kind;
    document.querySelectorAll('[data-kind]').forEach(n => n.classList.toggle('selected', n === b));
    render();
  });
}
function fileRow(name, meta, isFolder = false) {
  const row = document.createElement('div'); row.className = 'file-row';
  const icon = document.createElement('div'); icon.className = 'file-icon'; icon.textContent = isFolder ? '▣' : '▤';
  const label = document.createElement('div'); label.className = 'file-name'; label.textContent = name;
  const right = document.createElement('div'); right.className = 'file-meta'; right.textContent = meta;
  row.append(icon, label, right); return row;
}
function render() {
  const files = state.libraries?.[kind] || [];
  $('file-count').textContent = files.length ? `${files.length}` : '';
  $('library').replaceChildren(...(files.length ? files.map(f => fileRow(f.name, '', f.folder)) : [empty('Пусто')]));
  const active = state.torrents.filter(x => x.progress < 100).length;
  $('count').textContent = active ? ` ${active}` : '';
  $('torrent-state').textContent = state.torrentError ? 'Не подключен' : '';
  const torrentRows = state.torrents.map(x => {
    const row = fileRow(x.name, `${x.progress}% · ${byteSize(x.speed)}/с`);
    const body = row.querySelector('.file-name'); body.className = 'job-main';
    const bar = document.createElement('div'); bar.className = 'progress';
    const inner = document.createElement('div'); inner.style.width = `${x.progress}%`; bar.append(inner);
    body.append(bar); return row;
  });
  $('torrents').replaceChildren(...(torrentRows.length ? torrentRows : [empty(state.torrentError ? 'qBittorrent недоступен' : 'Нет загрузок')]));
  const used = state.disk.used, total = state.disk.total;
  $('disk').textContent = `Диск ${byteSize(used)} / ${byteSize(total)}`;
}
function empty(s) { const e = document.createElement('div'); e.className='empty'; e.textContent=s; return e; }
async function refresh() {
  try { state = await api('/api/state'); render(); } catch(e) { /* Preserve last state on temporary failures. */ }
}
$('torrent-form').addEventListener('submit', async e => {
  e.preventDefault(); const link = $('torrent-link').value.trim(); if (!link) return;
  const button = e.currentTarget.querySelector('button'); button.disabled = true;
  try {
    await api('/api/torrents', {method: 'POST', body: JSON.stringify({url: link, kind})});
    $('torrent-link').value = ''; toast('Добавлено'); refresh();
  } catch (e) { toast(errorMessage(e)); }
  finally { button.disabled = false; }
});
function validFile(f, category) {
  const ext = f.name.split('.').pop().toLowerCase();
  const videos = ['mkv','mp4','avi','mov','m4v','webm','ts','wmv','mpg','mpeg'];
  const audio = ['mp3','flac','m4a','aac','ogg','opus','wav','alac','wma'];
  return (category === 'music' ? audio : videos).includes(ext);
}
function renderUploads() {
  $('upload-jobs').replaceChildren(...uploads.map(j => {
    const row = document.createElement('div'); row.className = 'upload-job';
    const text = document.createElement('div'); text.className = 'file-row';
    const name = document.createElement('span'); name.className = 'file-name'; name.textContent = j.file.name;
    const progress = document.createElement('span'); progress.className = 'file-meta'; progress.textContent = `${Math.round(j.progress)}%`;
    text.append(name,progress);
    const bar = document.createElement('div'); bar.className = 'progress'; const inside = document.createElement('div'); inside.style.width = `${j.progress}%`; bar.append(inside);
    row.append(text,bar); return row;
  }));
}
function startUploads(files) {
  const category = kind;
  for (const file of files) {
    if (!validFile(file, category)) { toast(`Формат не поддерживается: ${file.name}`); continue; }
    const job = {file, progress: 0}; uploads.push(job); renderUploads();
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/upload?kind=${encodeURIComponent(category)}&name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = e => { if (e.lengthComputable) { job.progress = e.loaded/e.total*100; renderUploads(); } };
    xhr.onload = () => {
      uploads = uploads.filter(x => x !== job); renderUploads();
      if (xhr.status === 200) refresh();
      else { let msg = `Ошибка ${xhr.status}`; try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) {} toast(msg); }
    };
    xhr.onerror = () => { uploads = uploads.filter(x => x !== job); renderUploads(); toast('Ошибка соединения'); };
    xhr.send(file);
  }
}
const dropArea = $('drop-area');
dropArea.addEventListener('click', e => { if (e.target.id !== 'browse') $('file-input').click(); });
dropArea.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('file-input').click(); } });
$('browse').addEventListener('click', e => { e.stopPropagation(); $('file-input').click(); });
$('file-input').addEventListener('change', e => { startUploads([...e.target.files]); e.target.value=''; });
for (const event of ['dragenter','dragover']) dropArea.addEventListener(event, e => { e.preventDefault(); dropArea.classList.add('drag'); });
for (const event of ['dragleave','drop']) dropArea.addEventListener(event, e => { e.preventDefault(); dropArea.classList.remove('drag'); });
dropArea.addEventListener('drop', e => startUploads([...e.dataTransfer.files]));
$('jellyfin-link').href = `${location.protocol}//${location.hostname}:8096`;
$('navidrome-link').href = `${location.protocol}//${location.hostname}:4533`;
api('/api/session').then(showDashboard).catch(showLogin);
