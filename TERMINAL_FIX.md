# Как починить Terminal.app на Mac

## Быстро (часто хватает)

1. **Перезагрузите Mac** — лечит `The system has no more ptys` и «зависший» Terminal.
2. **Закройте лишние окна Terminal** и вкладки Cursor (View → Terminal).
3. Откройте **Terminal.app** заново (Программы → Утилиты → Terminal).

---

## Если Terminal открывается и сразу закрывается / пустой

В **Finder** откройте домашнюю папку (Cmd+Shift+H).

Переименуйте (если есть):

| Файл | Действие |
|------|----------|
| `.zshrc` | → `.zshrc.bak` |
| `.zprofile` | → `.zprofile.bak` |
| `.bash_profile` | → `.bash_profile.bak` |

Снова откройте Terminal — должен появиться обычный `%` или `$`.

Потом можно вернуть настройки из `.bak` по частям.

---

## Сброс настроек Terminal.app

1. Закройте Terminal.
2. Finder → **Переход → Переход к папке** (Cmd+Shift+G):
   `~/Library/Preferences/com.apple.Terminal.plist`
3. Переименуйте файл в `com.apple.Terminal.plist.bak`
4. Откройте Terminal — настройки как у нового.

---

## Деплой из Terminal (после починки)

```bash
cd ~/Projects/BOT/web_kp
export DEPLOY_PASS='пароль root'
export DISPLAY=:0
./deploy.sh
```

Должны идти строки `(1/7)…` … `VERIFY_OK`.

Проверка SSH отдельно:

```bash
export DEPLOY_PASS='пароль'
./test_ssh_askpass.sh
```

---

## Если снова «тишина» больше 45 секунд

```bash
ssh -v -o ConnectTimeout=12 root@72.56.237.74 echo OK
```

- Зависло на `Connecting` — сеть или сервер.
- `Permission denied` — неверный пароль.
- `no more ptys` — снова перезагрузка Mac.

---

## Cursor вместо Terminal.app

**View → Terminal** (Ctrl+`) — часто работает, когда Terminal.app сломан.

Те же команды деплоя.

---

## Не используйте для дизайна

- `restart_docker.command`
- `docker compose build` на сервере без rsync

Только `./deploy.sh`.
