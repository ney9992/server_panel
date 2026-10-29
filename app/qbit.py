"""Small async adapter for qBittorrent Web API v2."""
import httpx


class QBittorrent:
    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.client = httpx.AsyncClient(base_url=self.url, timeout=12, headers={
            'Origin': self.url, 'Referer': self.url + '/',
        })
        self.authenticated = False

    async def close(self):
        await self.client.aclose()

    async def login(self):
        if not self.password:
            raise RuntimeError('QBIT_PASSWORD не задан')
        response = await self.client.post('/api/v2/auth/login', data={
            'username': self.username, 'password': self.password,
        })
        response.raise_for_status()
        if response.text.strip() != 'Ok.':
            raise RuntimeError('Неверные учётные данные qBittorrent')
        self.authenticated = True

    async def request(self, method: str, path: str, **kwargs):
        if not self.authenticated:
            await self.login()
        response = await self.client.request(method, path, **kwargs)
        if response.status_code in (401, 403):
            self.authenticated = False
            await self.login()
            response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    async def list(self):
        return (await self.request('GET', '/api/v2/torrents/info')).json()

    async def files(self, torrent_hash: str):
        return (await self.request('GET', '/api/v2/torrents/files', params={'hash': torrent_hash})).json()

    async def add(self, link: str, kind: str):
        # qBittorrent requires categories to exist before assigning them.
        categories = (await self.request('GET', '/api/v2/torrents/categories')).json()
        if kind not in categories:
            response = await self.request('POST', '/api/v2/torrents/createCategory',
                                          data={'category': kind})
            response.raise_for_status()
        path = f'/data/downloads/complete/{kind}'
        response = await self.request('POST', '/api/v2/torrents/add', data={
            'urls': link, 'savepath': path, 'category': kind, 'autoTMM': 'false',
        })
        if response.text.strip() != 'Ok.':
            raise RuntimeError('qBittorrent не принял торрент')
