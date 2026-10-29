# Server Panel

Минималистичная панель для домашнего медиасервера на Linux: загрузка файлов через браузер, magnet/HTTP(S)-ссылки в qBittorrent, автоматическое добавление готовых видео и музыки в Jellyfin/Navidrome.

## Запуск (Debian/Ubuntu + Docker Compose)

```bash
cp .env.example .env
# Установите PANEL_PASSWORD и PANEL_SECRET в .env (секрет: openssl rand -hex 32)
mkdir -p data/media/{movies,series,music} data/downloads/complete/{movies,series,music} \
  data/qbittorrent data/jellyfin/{config,cache} data/navidrome
sudo chown -R "$(id -u):$(id -g)" data
# PUID/PGID в .env должны совпадать с владельцем data
docker compose up -d --build
```

Панель: `http://localhost:8090`. Для доступа из локальной сети в `.env` укажите `PANEL_BIND=<LAN_IP>` и `MEDIA_BIND=<LAN_IP>`, затем перезапустите сервисы. Не открывайте панель и qBittorrent в публичный интернет; для удалённого доступа используйте VPN (например, Tailscale) и HTTPS при необходимости. При работе через HTTPS укажите `COOKIE_SECURE=true`.

### qBittorrent (однократно)

1. Узнайте временный пароль: `docker compose logs qbittorrent` (строка с temporary password).
2. Откройте WebUI `http://localhost:8081` (с другого ПК через SSH-туннель), войдите пользователем `admin` и временным паролем.
3. Задайте постоянный пароль в настройках WebUI qBittorrent.
4. Укажите его как `QBIT_PASSWORD` в `.env` и выполните `docker compose up -d panel`.
5. Если запросы API отклоняются из-за Host header, добавьте `qbittorrent` в разрешённые домены WebUI (не отключайте проверку Host header для публичного доступа).

В медиатеке Jellyfin создайте библиотеки: `/media/movies` и `/media/series`. Для музыки Navidrome сканирует `/music`. После скачивания торрента панель каждые 20 секунд переносит готовые файлы в медиатеку **жёсткими ссылками** (либо копированием, если файловые системы разные): это сохраняет возможность раздачи. Файлы напрямую с ПК загружаются в соответствующие папки. Музыка поддерживает MP3, FLAC и другие распространённые форматы. Торренты используйте только для контента, который вправе скачивать.

Если Jellyfin не замечает новые файлы, включите мониторинг медиатеки или периодическое сканирование в настройках Jellyfin.

### Возможности

- Авторизация по логину/паролю, подписанная cookie, `HttpOnly` и `SameSite=Strict`.
- Drag & Drop видео/аудио (потоковая загрузка, без помещения всего файла в оперативную память), прогресс загрузки.
- Magnet и URL `.torrent` через qBittorrent Web API, прогресс скачивания.
- Статистика свободного места и список недавно добавленных файлов.
- Отдельные приложения Jellyfin (видео) и Navidrome (музыка).

### Безопасность и эксплуатация

- Не публикуйте HTTP-панель в интернет; используйте VPN/Tailscale и защищённое соединение.
- Храните `.env` в секрете и делайте бэкапы `data` на отдельный носитель.
- Отдавайте каталоги Jellyfin/Navidrome только на чтение (это уже задано в compose).
- Внешний диск можно подмонтировать вместо `./data`; убедитесь, что все контейнеры имеют права на запись.
- Для больших файлов рекомендуется подключать сервер и ПК по кабелю, использовать достаточно свободного места.
- Сервисы сознательно не запускают произвольные команды, не принимают пути файлов от браузера и не предоставляют доступ к Docker socket.

### Тесты

```bash
pip install -r requirements.txt pytest
PANEL_PASSWORD=testpass PANEL_SECRET=0123456789abcdef0123456789abcdef pytest -q
```

### Порты

| Сервис | Порт |
|---|---|
| Panel | 8090 |
| Jellyfin | 8096 |
| Navidrome | 4533 |
| qBittorrent WebUI | 8081 (только localhost) |
| Torrent P2P | 6881 TCP/UDP |
