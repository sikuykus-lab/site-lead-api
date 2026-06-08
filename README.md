# Lead API — заявки с сайта в Telegram

Короче: **POST JSON → проверки → sendMessage в CRM-группу**, stdlib HTTP, без Django.

Задача: форма на статическом лендинге не должна тянуть тяжёлый бэкенд. Один endpoint за nginx, антиспам встроен.

---

## Что сделано

- **POST /api/lead** — имя, телефон, сообщение, honeypot, timestamp формы.
- **Rate limit по IP** — in-memory, на типичной нагрузке хватает.
- **Чтение BOT_TOKEN из CRM .env** — один токен на цепочку.
- **Threading / stdlib** — мало зависимостей, легко на VPS.

---

## Фишки и удобство

| Фишка | Зачем |
|-------|-------|
| `hp` honeypot | Боты заполняют — отбой |
| `t0` min/max ms | Слишком быстрая отправка = бот |
| 127.0.0.1:8791 | Только через nginx, не в интернет |
| CRM_ENV_PATH | Не дублировать секреты |
| JSON без PII в логах | Минимум утечек |

---

## Схема данных

```mermaid
flowchart TB
  subgraph client ["Браузер"]
    F["Форма + hp + t0"]
  end

  subgraph edge ["VPS"]
    NGX["nginx"]
    API["Lead API :8791"]
  end

  subgraph tg ["Telegram"]
    TAPI["Bot API"]
    GRP["CRM-группа"]
  end

  F --> NGX
  NGX --> API
  API -->|"sendMessage"| TAPI
  TAPI --> GRP
```

---

## Процесс пользователя

```mermaid
flowchart LR
  A["Заполнил форму"] --> B["Отправить"]
  B --> C{"API OK?"}
  C -->|да| D["«Спасибо»"]
  C -->|нет| E["Ошибка /\nтихий отбой"]
  D --> F["Менеджер видит\nв группе"]
```

**Администратор / DevOps:**

```mermaid
flowchart TD
  R1["CRM .env\nBOT_TOKEN + GROUP_ID"] --> R2["site-lead-api.service"]
  R2 --> R3["nginx → :8791"]
  R3 --> R4["ALLOW_ORIGINS\nrate limit в env"]
```

---

## Стек

| Слой | Технология |
|------|------------|
| HTTP | Python 3 http.server / uwsgi |
| Прокси | nginx |
| Telegram | urllib → sendMessage |
| CRM | общий .env |

---

## Структура репозитория

```
README.md
LICENSE
.gitignore
server/site_lead_server.py
deploy/site-lead-api.service
docs/                     — DIAGRAMS.md (3× mermaid)
examples/.env.example
```

---

## Быстрый старт

```bash
export CRM_ENV_PATH="/opt/telegram_crm_bot/.env"
export SITE_LEAD_LISTEN="127.0.0.1:8791"
python3 site_lead_server.py
```

nginx: `location /api/lead { proxy_pass http://127.0.0.1:8791; }`
