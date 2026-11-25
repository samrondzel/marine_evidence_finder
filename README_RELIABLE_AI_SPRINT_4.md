# Marine Evidence Finder — Reliable AI Systems / Sprint 4: Agentic Research

**Основа:** уже установленные Sprint 1 (background ingestion), Sprint 2 (retries/recovery с исправленным RQ-cleanup), Sprint 3 (observability).

**Цель:** не прикрутить LangChain ради строчки в CV, а построить маленький, управляемый и тестируемый *agentic workflow*: LLM выбирает последовательность **разрешённых read-only инструментов**, Python исполняет их и проверяет ограничения, второй LLM-вызов генерирует ответ на основании реально найденных PDF-фрагментов. Оригинальные `/search` и `/ask` остаются нетронутыми.

## Что добавлено

| Файл | Назначение |
|---|---|
| `src/marine_evidence/agent.py` | Planner, два инструмента, step-budget, проверки, остановка, trace, synthesis |
| `src/marine_evidence/api.py` | `POST /agent/ask`, строгая валидация входа |
| `src/marine_evidence/observability.py` | Безопасные счётчики и histogram агентных запусков |
| `streamlit_app.py` | Режим `Agentic research`, отображение решений/инструментов |
| `observability/grafana/dashboards/marine_reliable_ai.json` | Две панели для агентных запусков и tool calls (старые панели сохранены) |
| `tests/test_agent.py` | Оффлайн-тесты поведения с подменным planner/generator |
| `scripts/smoke_agent.py` | Бесплатный офлайн smoke, опциональный платный live smoke |
| `scripts/eval_agent_vs_ask.py` | Опциональное сравнение с базовым `/ask` на gold-вопросах (платное) |
| `README_RELIABLE_AI_SPRINT_4.md` | Этот документ |

**Нет новых таблиц, миграций, Redis queues, контейнеров и секретов.** Применяется как ZIP-overlay поверх текущей версии. Сохраняйте свои локальные изменения перед распаковкой.

## 1. Установка (PowerShell, корень репозитория)

```powershell
$cfg = @(
  '-f', 'compose.yaml',
  '-f', 'compose.postgres.yaml',
  '-f', 'compose.metadata.yaml',
  '-f', 'compose.jobs.yaml',
  '-f', 'compose.observability.yaml'
)

git status --short
# Если есть незакоммиченные изменения в файлах из архива, сохраните их.
Expand-Archive `
  "$env:USERPROFILE\Downloads\marine_reliable_ai_sprint4_agentic_overlay.zip" `
  -DestinationPath . -Force

python -m pytest -q
python scripts/smoke_agent.py

docker compose @cfg up -d --build --no-deps api ui
docker compose @cfg restart grafana
docker compose @cfg ps
```

В проверенной копии проекта результат `pytest`: **138 passed, 5 skipped** (5 интеграционных тестов PostgreSQL требуют отдельного тестового окружения). Офлайн smoke использует детерминированные заглушки модели: **он не проверяет наличие OpenAI API key, фактическую работу OpenAI или Docker**.

> **Не делайте** `docker compose down -v`: это удалит volumes с данными. Не пересоздавайте PostgreSQL, Redis и worker ради новой read-only функции. Ваши PDF сохраняются.

## 2. Проверка API без платы за LLM

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
python scripts/smoke_agent.py
```

Маршрут `/agent/ask` доступен в OpenAPI: <http://127.0.0.1:8000/docs>. Но **реальные** запросы к нему требуют `OPENAI_API_KEY` в `.env`, уже используемый вашим `/ask`.

## 3. Проверка настоящего Agentic AI (расходует API-токены)

Убедитесь, что в `.env` настроено `OPENAI_API_KEY`. Не печатайте его в чат и не коммитьте.

```powershell
python scripts/smoke_agent.py --live `
  --question "How did vessel noise affect porpoise foraging in the indexed studies?"
```

Или через Streamlit: <http://127.0.0.1:8501> → `Agentic research (OpenAI API)` → модель `gpt-5-mini` → `Max steps = 5` → вопрос → `Generate answer`.

Если ключ отсутствует в контейнере API или сеть/лимиты OpenAI недоступны, endpoint может вернуть HTTP 503/502. Это не доказательство дефекта поиска. Для проверки наличия переменной без показа значения:

```powershell
docker compose @cfg exec api python -c "import os; print('key configured:', bool(os.getenv('OPENAI_API_KEY')))"
```

Пример прямого вызова:

```powershell
$body = @{
  question = 'How did vessel noise affect porpoise foraging in the indexed studies?'
  model = 'gpt-5-mini'
  top_k = 4
  max_steps = 5
  distinct_pages = $false
} | ConvertTo-Json

$result = Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8000/agent/ask' `
  -Method POST -ContentType 'application/json' `
  -Body $body -TimeoutSec 270

$result | ConvertTo-Json -Depth 8
```

Ответ содержит `status`, `claims`, `reason`, `citations`, `retrieved`, `trace`, `steps`, `tool_calls`, `stop_reason`, `elapsed_ms` и `model`. Возможен `insufficient_evidence` — это корректный исход, если наш небольшой BM25-корпус не подтверждает запрос, агент исчерпал бюджет или остановился.

## 4. Архитектура и алгоритм

```text
POST /agent/ask
    |
    v
snapshot_index() -> BM25Index  (актуальные PDF + PostgreSQL metadata)
    |
    v
Planner (LLM, JSON schema)  -----------+ 
    |                                     ^
    +-- search_bm25(query) -------------->|
    |     local BM25; max 6 hits/query    |
    +-- expand_context(known_chunk_id) -->|
    |     only adjacent same-source      |
    |     passages; no arbitrary reads   |
    +-- abstain -> insufficient_evidence |
    +-- finish -> validated generator ---+
                        |
                        v
              validated claims + citation_ids
                        |
                        v
        HTTP response + bounded tool trace + safe metrics
```

Фактически это цикл **Plan → Tool → Observe → Plan → ... → Finish/Abstain**. Это не нативный OpenAI function calling: planner выбирает действие через строгий JSON schema; Python сам вызывает один из whitelisted инструментов. LLM ни при каких условиях не получает `exec()`, shell, доступ к интернету, удаление PDF или произвольный SQL.

### Шаг A: Planner

`call_agent_planner()` использует OpenAI Responses API со структурированным ответом:

```json
{"action":"search_bm25","query":"porpoise foraging vessel noise","chunk_id":"","note":"Find direct measurements"}
```

Другие разрешённые значения `action`: `expand_context`, `finish`, `abstain`. JSON-поля обязательны, неизвестные запрещены. **`note` — короткое операционное объяснение, а не скрытая цепочка размышлений.**

### Шаг B: Tool execution

Выполняет Python (`run_research_agent()`), а не модель. `search_bm25` использует уже существующий индекс и может корректировать запрос при следующем шаге. `expand_context` принимает **только `chunk_id`, уже полученный из поиска**, и добавляет максимум двух соседей в пределах того же документа и соседних страниц. Дубликаты исключены. Максимум 12 уникальных фрагментов в общем evidence set.

История следующих вызовов включает ограниченные excerpts (до 650 символов на passage), `chunk_id`, источник, страницу и предыдущие действия. Полные PDF **никогда** не отдаются модели, и данные из PDF объявлены недоверенными.

### Шаг C: Finish

Если есть фрагменты, вызывается уже существующий `answer.call_openai()` с **полным текстом только собранных evidence passages** и его же `validate_answer()`.

- `answered`: 1–8 утверждений, каждое с одним или несколькими существующими `chunk_id`.
- `insufficient_evidence`: нет утверждений, есть объяснение недостающих данных.
- Пустой набор evidence не вызывает платный генератор.
- Несуществующая ссылка/неверный JSON -> исключение/HTTP 502 (fail closed), а не фальшивый ответ.

**Наличие действительного ID цитаты не доказывает, что цитата действительно поддерживает утверждение**. Проверку entailment, качество ответа и ограничения BM25 необходимо оценивать отдельно.

### Шаг D: Boundaries and stopping

- `max_steps`: 2–6, значение по умолчанию 5. Один шаг = одно решение planner, в том числе `finish`.
- `top_k`: 1–6 для каждой поисковой операции, значение по умолчанию 4.
- `MAX_EVIDENCE=12`: максимум накопленных уникальных passage.
- Повтор такого же нормализованного запроса немедленно останавливает цикл.
- Нельзя expand неизвестный chunk ID или expand один и тот же ID два раза.
- Если бюджет закончился до `finish`, возвращаем `insufficient_evidence`, не генерируем ответ автоматически по случайно найденным отрывкам.
- Один planner-вызов: OpenAI timeout 30 секунд и max_retries=1; synthesis использует существующие лимиты `answer.py`.
- **Нет глобального wall-clock timeout, нет rate limiting/аутентификации, нет долгосрочной памяти агента**. В текущем локальном MVP это осознанные ограничения.

## 5. Наблюдаемость (Sprint 3)

Структурированные события:

- `agent_tool_completed` (тип инструмента и количество добавленных фрагментов),
- `agent_run_completed` (статус, шаги, число инструментов, длительность).

Ни исследовательский вопрос, ни тексты PDF, ни имена документов **не логируются как структурированные поля**. Однако прочие компоненты/исключения надо аудировать отдельно перед публичным deployment.

Новые метрики Prometheus:

```promql
sum by (outcome,stop_reason) (rate(marine_agent_runs_total[5m]))
sum by (tool) (rate(marine_agent_tool_calls_total[5m]))
rate(marine_agent_run_duration_seconds_sum[5m])
  / rate(marine_agent_run_duration_seconds_count[5m])
```

`job_id`, `chunk_id`, query **не используются в labels**, чтобы не создать high cardinality. После запроса открой <http://127.0.0.1:3000/d/marine-reliable-ai-s3> — две новые панели находятся в нижней части старого dashboard. До первого запуска агента панели могут отображать `No data`.

## 6. Приёмочные тесты

1. `python -m pytest -q` → 138 passed, 5 skipped на проверенной копии.
2. `python scripts/smoke_agent.py` → `PASS` без OpenAI и Docker.
3. Живой вопрос из существующего корпуса: `/agent/ask` отвечает `answered` либо честно `insufficient_evidence`, содержит `trace`.
4. В trace виден хотя бы один `search_bm25` для поискового сценария. В отдельных сценариях модель может выбрать `abstain` сразу — это валидное действие.
5. `citations[].chunk_id` каждый есть в `retrieved[].chunk_id`.
6. Prometheus после реального запроса показывает `marine_agent_runs_total`, а Grafana новые панели.
7. Попробовать вопрос, ответа на который нет в корпусе. Проверить abstention (или заметить слабость модели, если она всё же отвечает — semantic entailment не проверяется автоматически).
8. Сравнить с `POST /ask` на тех же 3–5 вопросах через `scripts/eval_agent_vs_ask.py`. **Оценивать: точность научных выводов, полноту цитат, долю abstentions, число LLM-вызовов, latency и стоимость**. Agent должен оправдывать себя качеством, не только «автономностью».

### Проверка полезности против обычного RAG (опционально, платная)

После базовой приёмки сравните на заранее зафиксированной dev-выборке:

```powershell
python scripts/eval_agent_vs_ask.py --confirm-paid --split dev --limit 3 `
  --output data/agent_dev_comparison.jsonl
```

Скрипт вызывает **оба** endpoint и печатает status, latency, proxy source-recall, tool calls. `gold_answer`, `required_facts` и `forbidden_claims` **не отправляются LLM**; они только для оценки после ответа. Сохранённые `claims` и citation IDs надо оценить вручную. Не называйте source-recall полноценной оценкой scientific accuracy. Не делайте тюнинг на `test`-split после просмотра его gold.

## 7. Интервью: что нужно объяснить

1. Чем обычный RAG (`retrieve → generate`) отличается от agentic retrieval (`plan → tool → observe → ... → generate`)?
2. Почему нужен Python tool dispatcher, даже если LLM может вернуть JSON?
3. Что защищает от prompt injection, а что всё ещё уязвимо?
4. Что означает idempotency/read-only tool и почему мы не разрешили `delete_document`?
5. В чём различие `max_steps`, `top_k` и `MAX_EVIDENCE`?
6. Почему мы не генерируем ответ, если planner исчерпал бюджет, но не выбрал `finish`?
7. Как работают citation allowlist и fail-closed validation?
8. Почему tool trace — не то же, что раскрытие chain-of-thought?
9. Как измерить, что агент действительно улучшил ответы по сравнению с `/ask`, а не просто увеличил стоимость?
10. Что потребуется для production: auth, rate limiting, total wallclock budget, async execution, distributed tracing, semantic judge + human evaluation, cost accounting?

## 8. Честные ограничения

- Нельзя считать вывод «факт проверен» только из-за существующей ссылки. Цитата может быть логически нерелевантной.
- BM25 остаётся лексическим; агент может подбирать слова, но не создаёт семантический поиск из воздуха.
- Каждый шаг planner и финальный synthesis — **платные внешние API-вызовы**.
- Инструмент `expand_context` использует физически соседние чанки из массива индекса, а не гарантированное семантическое разбиение на параграфы.
- Endpoint синхронный и не хранит состояние агентного цикла после рестарта API; длительные workflow в следующих спринтах можно перевести в durable jobs.
- Нельзя публиковать приложение без аутентификации, квот и TLS. Прежние локальные Docker-порты ограничены localhost.
- Метрики учитывают завершённые запросы; неудачные вызовы LLM отражаются HTTP 5xx, но в `marine_agent_runs_total` не попадают.

**Definition of Done:** офлайн тесты + живая агентная обработка + trace/citations + метрики; потом ручная оценка нескольких реальных вопросов против простого `/ask`.
