"""Self-hosted, minimal media upload and torrent dashboard."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .qbit import QBittorrent

LOG = logging.getLogger('server_panel')
ROOT = Path(os.environ.get('DATA_ROOT', '/data')).resolve()
MEDIA = ROOT / 'media'
DOWNLOADS = ROOT / 'downloads' / 'complete'
KINDS = {'movies', 'series', 'music'}
VIDEO_EXT = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.webm', '.ts', '.wmv', '.mpg', '.mpeg'}
AUDIO_EXT = {'.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.alac', '.wma'}
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_GB', '100')) * 1024 ** 3
USERNAME = os.getenv('PANEL_USERNAME', 'admin')
PASSWORD = os.getenv('PANEL_PASSWORD', '')
SECRET = os.getenv('PANEL_SECRET', '')
SECURE_COOKIE = os.getenv('COOKIE_SECURE', 'false').lower() in ('true', '1')
SESSION_AGE = 60 * 60 * 24 * 14
STATIC = Path(__file__).resolve().parent / 'static'

if not PASSWORD or not SECRET or len(SECRET) < 32:
    raise RuntimeError('Задайте PANEL_PASSWORD и PANEL_SECRET (минимум 32 символа)')

signer = URLSafeTimedSerializer(SECRET, salt='server-panel-session')
qbit = QBittorrent(os.getenv('QBIT_URL', 'http://qbittorrent:8080'),
                  os.getenv('QBIT_USERNAME', 'admin'), os.getenv('QBIT_PASSWORD', ''))
status_error = ''
last_sync = 0.0


def safe_name(name: str) -> str:
    """Flatten file upload names; preserve Unicode; protect Windows/Unix controls."""
    name = (name or '').replace('\\', '/').split('/')[-1].strip().strip('.')
    name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', '_', name)
    if not name or name in ('.', '..') or len(name.encode('utf-8')) > 230:
        raise HTTPException(400, 'Некорректное имя файла')
    return name


def extension_allowed(name: str, kind: str) -> bool:
    return Path(name).suffix.lower() in (AUDIO_EXT if kind == 'music' else VIDEO_EXT)


def unique_path(folder: Path, name: str) -> Path:
    dest = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while dest.exists():
        dest = folder / f'{stem} ({counter}){suffix}'
        counter += 1
    return dest


def verify_session(request: Request):
    token = request.cookies.get('panel_session')
    if not token:
        raise HTTPException(401, 'Требуется вход')
    try:
        value = signer.loads(token, max_age=SESSION_AGE)
        if value != USERNAME:
            raise ValueError('Некорректная сессия')
    except (BadSignature, SignatureExpired, ValueError):
        raise HTTPException(401, 'Требуется вход') from None


def verify_origin(request: Request):
    # Browser POSTs always include an Origin; reject cross-site submissions.
    origin = request.headers.get('origin')
    if origin:
        parsed = urlparse(origin)
        if parsed.netloc.lower() != request.headers.get('host', '').lower() or parsed.scheme not in ('http', 'https'):
            raise HTTPException(403, 'Недопустимый источник')


def file_within(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


async def sync_media():
    """Hardlink completed torrents into media without interrupting torrent seeding."""
    torrents = await qbit.list()
    imported = 0
    for torrent in torrents:
        kind = torrent.get('category', '')
        if kind not in KINDS or float(torrent.get('progress') or 0) < 1:
            continue
        save_path = Path(torrent.get('save_path') or '').resolve()
        allowed_root = DOWNLOADS / kind
        if not file_within(save_path, allowed_root):
            continue
        try:
            files = await qbit.files(torrent['hash'])
        except Exception:
            LOG.exception('Не удалось прочитать список файлов торрента')
            continue
        for entry in files:
            raw = entry.get('name') or ''
            rel = Path(raw)
            if not raw or rel.is_absolute() or '..' in rel.parts or not extension_allowed(raw, kind):
                continue
            source = save_path / rel
            if not file_within(source, allowed_root) or not source.is_file():
                continue
            if float(entry.get('progress', 0)) < 1:
                continue
            target = MEDIA / kind / rel
            if not file_within(target, MEDIA / kind):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not os.path.samefile(source, target):
                # Stable collision name to avoid reimporting on every scan.
                h = torrent['hash'][:10]
                target = target.with_name(f'{target.stem} [{h}]{target.suffix}')
            if target.exists():
                continue
            try:
                os.link(source, target)
            except OSError:
                # Different filesystems: copy safely via an intermediate file.
                tmp = target.with_name('.' + uuid.uuid4().hex + '.partial')
                try:
                    shutil.copy2(source, tmp)
                    os.replace(tmp, target)
                finally:
                    tmp.unlink(missing_ok=True)
            imported += 1
    return imported


async def media_worker():
    global status_error, last_sync
    while True:
        try:
            await sync_media()
            status_error = ''
            last_sync = time.time()
        except Exception as exc:
            status_error = str(exc)[:160]
            LOG.warning('qBittorrent не подключён: %s', exc)
        await asyncio.sleep(20)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for kind in KINDS:
        (MEDIA / kind).mkdir(parents=True, exist_ok=True)
        (DOWNLOADS / kind).mkdir(parents=True, exist_ok=True)
    worker = asyncio.create_task(media_worker())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        await qbit.close()


app = FastAPI(title='Server Panel', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.get('/')
async def index():
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/api/session')
async def session(request: Request):
    verify_session(request)
    return {'user': USERNAME}


@app.post('/api/login')
async def login(request: Request):
    verify_origin(request)
    payload = await request.json()
    if not isinstance(payload, dict) or not (hmac.compare_digest(str(payload.get('user', '')), USERNAME) and
                                             hmac.compare_digest(str(payload.get('password', '')), PASSWORD)):
        raise HTTPException(401, 'Неверный логин или пароль')
    response = JSONResponse({'ok': True})
    response.set_cookie('panel_session', signer.dumps(USERNAME), httponly=True,
                        secure=SECURE_COOKIE, samesite='strict', max_age=SESSION_AGE, path='/')
    return response


@app.post('/api/logout')
async def logout(request: Request):
    verify_session(request)
    verify_origin(request)
    response = JSONResponse({'ok': True})
    response.delete_cookie('panel_session', path='/')
    return response


@app.get('/api/state')
async def state(request: Request):
    verify_session(request)
    disk = shutil.disk_usage(ROOT)
    libraries = {}
    for kind in KINDS:
        items = []
        for p in sorted((MEDIA / kind).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if p.is_file() and extension_allowed(p.name, kind) or p.is_dir():
                items.append({'name': p.name, 'folder': p.is_dir()})
            if len(items) == 30:
                break
        libraries[kind] = items
    torrents, error = [], status_error
    try:
        for t in await qbit.list():
            if t.get('category') not in KINDS:
                continue
            torrents.append({
                'hash': t.get('hash', ''), 'name': t.get('name', ''), 'category': t.get('category', ''),
                'progress': round(float(t.get('progress') or 0) * 100, 1),
                'speed': int(t.get('dlspeed') or 0), 'state': t.get('state', ''),
            })
        error = ''
    except Exception as exc:
        error = str(exc)[:150]
    return {
        'libraries': libraries, 'torrents': torrents[:100], 'torrentError': error,
        'disk': {'used': disk.used, 'total': disk.total},
    }


@app.post('/api/upload')
async def upload(request: Request, kind: str, name: str):
    verify_session(request)
    verify_origin(request)
    if kind not in KINDS:
        raise HTTPException(400, 'Неизвестная категория')
    clean_name = safe_name(name)
    if not extension_allowed(clean_name, kind):
        raise HTTPException(400, 'Неподдерживаемый формат')
    dest_dir = MEDIA / kind
    temp = dest_dir / f'.{uuid.uuid4().hex}.partial'
    transferred = 0
    try:
        with temp.open('xb') as out:
            async for chunk in request.stream():
                transferred += len(chunk)
                if transferred > MAX_UPLOAD:
                    raise HTTPException(413, 'Файл слишком большой')
                out.write(chunk)
        if not transferred:
            raise HTTPException(400, 'Пустой файл')
        # Atomic no-overwrite publish; concurrent uploads cannot clobber files.
        while True:
            dest = unique_path(dest_dir, clean_name)
            try:
                os.link(temp, dest)
                break
            except FileExistsError:
                continue
        return {'ok': True, 'file': dest.name}
    finally:
        temp.unlink(missing_ok=True)


@app.post('/api/torrents')
async def add_torrent(request: Request):
    verify_session(request)
    verify_origin(request)
    data = await request.json()
    kind = data.get('kind') if isinstance(data, dict) else None
    link = str(data.get('url', '')).strip() if isinstance(data, dict) else ''
    if kind not in KINDS or len(link) > 8192:
        raise HTTPException(400, 'Некорректные параметры')
    parsed = urlparse(link)
    if parsed.scheme not in ('magnet', 'http', 'https'):
        raise HTTPException(400, 'Нужна magnet- или HTTP(S)-ссылка')
    if parsed.scheme == 'magnet' and not any(
        value.startswith(('urn:btih:', 'urn:btmh:')) for value in parse_qs(parsed.query).get('xt', [])
    ):
        raise HTTPException(400, 'Некорректная magnet-ссылка')
    if parsed.scheme != 'magnet' and not parsed.hostname:
        raise HTTPException(400, 'Некорректная ссылка')
    try:
        await qbit.add(link, kind)
    except Exception as exc:
        raise HTTPException(502, f'qBittorrent: {str(exc)[:160]}') from None
    return {'ok': True}
