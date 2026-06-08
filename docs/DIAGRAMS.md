# Диаграммы

Три вида схемы — как в [dataroom-cms](https://github.com/sikuykus-lab/dataroom-cms):
**данные**, **взаимодействие пользователя**, **процессы администратора**.

Рендер: скопировать блок в [mermaid.live](https://mermaid.live).

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

## Процесс пользователя

```mermaid
flowchart LR
  A["Заполнил форму"] --> B["Отправить"]
  B --> C{"API OK?"}
  C -->|да| D["«Спасибо»"]
  C -->|нет| E["Ошибка /\nтихий отбой"]
  D --> F["Менеджер видит\nв группе"]
```

## Процессы администратора

```mermaid
flowchart TD
  R1["CRM .env\nBOT_TOKEN + GROUP_ID"] --> R2["site-lead-api.service"]
  R2 --> R3["nginx → :8791"]
  R3 --> R4["ALLOW_ORIGINS\nrate limit в env"]
```
