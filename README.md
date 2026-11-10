# Вариант 15. Генерация EAN-8 в PDF

Тема курсовой: «Веб-приложение с HTTP API для асинхронной генерации
штрих-кодов EAN-8 в формате PDF». Python 3.11+.

## Этап 1

Установка: `python -m pip install -e ".[test]"`.
CLI принимает путь к UTF-8 JSON-файлу с единственным полем `codes`:
списком от 1 до 100 строк. Для семи цифр вычисляется контрольная цифра,
для восьми проверяется существующая. Ведущие нули сохраняются.
Неверные данные приводят к коду завершения 2 и сообщению в stderr.
PDF записывается в stdout, по 10 этикеток на странице A4.

В `cmd.exe` (из PowerShell вызывайте через `cmd /c`):

```bat
ean8-cli examples/01_single.json > single.pdf
ean8-cli examples/02_complete.json > complete.pdf
ean8-cli examples/03_leading_zero.json > leading-zero.pdf
ean8-cli examples/04_batch.json > batch.pdf
ean8-cli examples/05_multipage.json > multipage.pdf
```

Для старых версий PowerShell перенаправление бинарного stdout через `>`
может портить PDF, поэтому используйте `cmd.exe` или `subprocess`.
Тестирование: `python -m pytest tests/test_barcode.py`.
Генерация изображения штрих-кода не регистрирует GTIN в GS1.

Контрольная цифра:
`(10 - (3*d1 + d2 + 3*d3 + d4 + 3*d5 + d6 + 3*d7) % 10) % 10`.
Источники: [GS1](https://www.gs1.ch/en/barcodes-standards/check-digit-calculator),
[RFC 7617](https://www.rfc-editor.org/rfc/rfc7617.html).

## Быстрый запуск на Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[test]"
Copy-Item config.example.ini config.ini
.\.venv\Scripts\ean8-server --config config.ini
```

Или запустите `run.bat`: он создаёт окружение, устанавливает зависимости,
копирует пример конфигурации при её отсутствии и запускает сервер.
Далее во втором терминале:

```powershell
.\.venv\Scripts\python scripts/demo_examples.py
.\.venv\Scripts\python scripts/demo_client.py
```

`demo_client.py` выполняет реальные HTTP-запросы, ожидает результат
асинхронной задачи и сохраняет `output/pdf/api-result.pdf`.
Пять примеров этапа 1 разобраны в [демонстрации](docs/stage1-examples.md).

## Этап 2: архитектура и схема данных

Bottle принимает запрос, сохраняет Message с `completed=0`, ставит задачу
в ThreadPoolExecutor и сразу возвращает XML с идентификатором.
Фоновый поток через `subprocess.run` запускает CLI с временным JSON-файлом.
stdout содержит PDF; stderr и ненулевой код завершения становятся ошибкой.
После обработки атомарно сохраняются Feedback и `completed=1`.
Клиент опрашивает `feedback-collect` и декодирует Base64.

Схема данных соответствует рисунку 15. На этапе 3 записи хранятся
в SQLite (`data/database.sqlite`) через SQLAlchemy ORM:

| Таблица | Поля |
|---|---|
| Account | uid: int, timestamp: int, ip: str |
| Message | uid: int, timestamp: int, argument: str, account: int, completed: int |
| Feedback | uid: int, timestamp: int, result: str, status: str, failure: str, message: int |

Внешние ключи проверяются при создании и изменении. `timestamp` - Unix time
в секундах, `completed` - 0 или 1. `argument` - JSON-строка формата этапа 1.
`result` - PDF в Base64; `status` - `succeeded` или `failed`;
`failure` - диагностический текст. В тестовом режиме результат пустой,
статус успешный, CLI не запускается.

Каждая операция открывает отдельную Session. Создание Feedback и установка
`completed=1` выполняются в одной транзакции. Проверка внешних ключей SQLite
включается для каждого подключения. При остановке сервер дожидается фоновых
задач и освобождает подключения. Незавершённые задания повторно ставятся
в очередь после перезапуска. Гарантия exactly-once при аварии не заявляется.

## Этап 3: SQLite и SQLAlchemy ORM

`models.py` описывает таблицы Account, Message и Feedback с первичными
и внешними ключами. `storage.py` реализует операции через SQLAlchemy ORM.
Методы HTTP API и формат XML сохранены; MBT проверяет API с настоящей SQLite.
Отчёт использует левое внешнее соединение, фильтр времени и DISTINCT.
После фильтра по Account.timestamp результат эквивалентен полному внешнему
соединению из формулы 15: строки без Account не проходят условие времени.

В `config.ini` укажите `database = data/database.sqlite`. Старый JSON-файл
не преобразуется автоматически и может храниться отдельно. Для установки
SQLAlchemy используйте команду установки зависимостей из раздела запуска.
Запуск сервера, демонстрационного клиента и `scripts/check.bat` не изменился.

## Маршруты HTTP API

Префикс всех маршрутов: `/core/api/`. Ответы - XML в UTF-8.
Имена методов ApiClient повторяют `метод_таблица_действие`, например
`post_message_submit`, `patch_account_modify`, `get_report_collect`.
Все 11 методов определены в `src/ean8_service/client.py`.

| Метод | Маршрут | Параметры |
|---|---|---|
| POST | account-submit | query: ip |
| GET | account-collect | query: ip, timestamp (необязательные фильтры) |
| GET | account-inspect | query: uid |
| PATCH | account-modify/:uid | XML: ip и/или timestamp |
| POST | message-submit | query: account, argument |
| GET | message-collect/:account | query: completed, timestamp, argument (фильтры) |
| GET | message-inspect | query: uid |
| PATCH | message-modify/:uid | XML: account и/или timestamp |
| GET | feedback-collect/:message | query: status, timestamp (фильтры) |
| GET | feedback-inspect | query: uid |
| GET | report-collect | нет |

Фильтры сопоставляются на равенство и объединяются через AND.
Изменение Message управляет принадлежностью и временем записи; входной
`argument` принятой задачи и вычисляемый `completed` доступны только для
чтения. Для других входных данных создаётся новая задача.
Идентификаторы генерирует сервер, Feedback создаёт только исполнитель.
Для PATCH подходит плоский XML, например
`<record><ip>10.0.0.15</ip></record>`.

Успешные операции, включая POST, возвращают `200 OK` по заданию.
Отсутствующие/неверные credentials возвращают `401 Unauthorized` с
`WWW-Authenticate: Basic realm="ean8", charset="UTF-8"`.
Неверные параметры, XML и неизвестные записи возвращают XML с `400`.
Пустой поиск возвращает `<response />`, коллекция - элементы `<item>`.
Авторизация применяется ко всем 11 обработчикам. Для доступа через внешнюю
сеть Basic Auth требует HTTPS на обратном прокси согласно RFC 7617.

Формула (15) реализована как множество уникальных пар `(Account.ip,
Message.argument)` для Account за последние 8 минут. При отсутствии задач
аккаунт включается с `<argument null="true" />`, как требует полное внешнее
соединение. Сообщения без аккаунта не могут пройти условие по его времени.

Пример запроса (в PowerShell используйте именно `curl.exe`):

```powershell
curl.exe -u student:change-me -X POST "http://127.0.0.1:8080/core/api/account-submit?ip=127.0.0.1"
curl.exe -u student:change-me "http://127.0.0.1:8080/core/api/report-collect"
```

## Настройки и функции

Конфигурация `config.ini`, секция `[server]`:

| Параметр | Значение примера | Назначение |
|---|---|---|
| host | 127.0.0.1 | Адрес прослушивания |
| port | 8080 | HTTP-порт |
| username | student | Имя для Basic Auth |
| password | change-me | Пароль, замените перед внешним доступом |
| database | data/database.sqlite | Путь относительно конфигурационного файла |
| test_mode | false | true: обработка без запуска CLI и без PDF |
| workers | 2 | Число параллельных исполнителей |
| timeout | 30 | Тайм-аут CLI в секундах |

Исходный код разделён по назначению. Публичные функции и методы имеют
docstring:

| Модуль | Основные функции |
|---|---|
| barcode | normalize: контрольная цифра; validate: входные данные; generate: PDF |
| cli | main: чтение файла, stdout/stderr и код завершения |
| storage | Store: create, collect, inspect, modify, finish, report |
| models | Base, Account, Message, Feedback: описание таблиц SQLAlchemy |
| server | main: запуск сервера; process_message, convert: обработка задания |
| api | create_app и регистрация маршрутов, protect, проверка параметров |
| xmlio | serialize: XML-ответ; parse: плоский XML PATCH |
| client | ApiClient: 11 методов и HTTP-транспорт на urllib |
| server | main: конфигурация, восстановление очереди, запуск Bottle |

## Проверки и покрытие

Соответствие правилам оформления из начала сборника проверяется командой
`python scripts/check_style.py`. Проверяются PEP 8, имена, сложность,
размеры файлов и функций, аргументы, комментарии, числовые сравнения,
структура Git и коммиты. Предел сложности принят равным 10, поскольку
в сборнике число не задано. [Таблица соответствия](docs/code-style.md).

```powershell
.\scripts\check.bat
```

Скрипт сначала проверяет алгоритм и PDF, затем запускает только Hypothesis
RuleBasedStateMachine для измерения покрытия HTTP-обработчиков:

```powershell
python -m coverage run --branch --source=ean8_service.api -m pytest tests/test_api_mbt.py -q
python -m coverage report --fail-under=100
python -m coverage html -d output/coverage
python -m coverage json -o output/coverage.json
```

`test_api_mbt.py` сравнивает API с независимой моделью Account, Message,
Feedback и отчёта, проверяет фильтры, авторизацию, XML-ошибки, перезагрузку
базы SQLite, тестовый режим и реальные subprocess. Запросы выполняются
API-клиентом; некорректные запросы проверяются напрямую через WSGI-транспорт
WebTest.
Ручные запросы и тесты CLI не включаются в отчёт покрытия API.
HTML-отчёт открывается через `output/coverage/index.html`.
Полученный результат: 100% операторов и ветвей модуля API.
Подробный [протокол проверки](docs/validation.md) сохранён в репозитории.

Полный набор: `python -m pytest`. Сборка: `python -m pip wheel --no-deps .`.
Дополнительные артефакты и PDF исключены через `.gitignore`.

## Сдача

Этапы сохранены отдельными коммитами Conventional Commits. Локальный
репозиторий подготовлен; для выполнения требования публичного доступа
создайте пустой репозиторий на выбранном git-сервисе и выполните:

```powershell
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin master
```

## ?????????? ???? ???????

?????????? ?????? ??????? ????????? ?? ?? docstring. ???????? ????????
???, ?????, ????????? ??????????? ? ??????? ????????.

### src/ean8_service/api.py

| ??????? | ?????????? |
|---|---|
| `authorized` | Check a UTF-8 Basic credential pair without logging secrets. |
| `protect` | Wrap every route with authentication and uniform XML errors. |
| `protect.decorate` | Attach the authentication and error-response wrapper. |
| `protect.decorate.wrapped` | Return a serialized result or a serialized client error. |
| `query_fields` | Read and type-check query fields, rejecting unknown names. |
| `checked` | Validate the explicitly supported mutable fields. |
| `patch_fields` | Read a bounded XML PATCH body. |
| `create_app` | Build an application with storage and a background submit call. |
| `create_app.get_report_collect` | Return distinct IP/argument pairs for recent accounts. |
| `register_accounts` | Register all four Account operations. |
| `register_accounts.post_account_submit` | Create an account using query-string parameters. |
| `register_accounts.get_account_collect` | Search accounts using exact-match filters. |
| `register_accounts.get_account_inspect` | Read an account identified by query-string uid. |
| `register_accounts.patch_account_modify` | Update mutable account fields from XML. |
| `register_messages` | Register immutable job submissions and mutable ownership metadata. |
| `register_messages.post_message_submit` | Validate, persist and asynchronously enqueue a generation job. |
| `register_messages.get_message_collect` | Search jobs belonging to the account in the path. |
| `register_messages.get_message_inspect` | Read a job identified by query-string uid. |
| `register_messages.patch_message_modify` | Change ownership or timestamp while preserving job input. |
| `register_feedback` | Expose generated results through the two read-only endpoints. |
| `register_feedback.get_feedback_collect` | Search results associated with the job in the path. |
| `register_feedback.get_feedback_inspect` | Read one terminal execution result. |

### src/ean8_service/barcode.py

| ??????? | ?????????? |
|---|---|
| `normalize` | Append or verify the GS1 modulo-10 check digit. |
| `validate` | Return normalized codes from a JSON object. |
| `generate` | Generate A4 PDF bytes with up to ten EAN-8 labels per page. |

### src/ean8_service/cli.py

| ??????? | ?????????? |
|---|---|
| `main` | Run the stage-one command-line converter. |

### src/ean8_service/client.py

| ??????? | ?????????? |
|---|---|
| `ApiClient.__init__` | Configure the base URL, credentials and optional WSGI adapter. |
| `ApiClient._http` | Perform a real HTTP request with a bounded connection timeout. |
| `ApiClient._call` | Serialize request parameters and decode the XML response. |
| `ApiClient.post_account_submit` | Create an account with a validated IP address. |
| `ApiClient.get_account_collect` | Search accounts by IP and/or timestamp. |
| `ApiClient.get_account_inspect` | Read one account. |
| `ApiClient.patch_account_modify` | Modify account IP or timestamp using an XML body. |
| `ApiClient.post_message_submit` | Submit a JSON argument string as query parameters. |
| `ApiClient.get_message_collect` | Search messages belonging to an account. |
| `ApiClient.get_message_inspect` | Read one job and its completed flag. |
| `ApiClient.patch_message_modify` | Modify job account or timestamp using an XML body. |
| `ApiClient.get_feedback_collect` | Find results for one job, optionally filtered by status. |
| `ApiClient.get_feedback_inspect` | Read a result: PDF Base64, status, and diagnostic failure. |
| `ApiClient.get_report_collect` | Read the report defined by formula 15. |

### src/ean8_service/server.py

| ??????? | ?????????? |
|---|---|
| `main` | Start one process; resume jobs left pending after an interruption. |

### src/ean8_service/storage.py

| ??????? | ?????????? |
|---|---|
| `enable_foreign_keys` | Enable SQLite foreign key checks on each connection. |
| `Store.__init__` | Create the SQLite engine and missing ORM tables. |
| `Store.collect` | Return a detached list of matching records. |
| `Store.inspect` | Find a record or raise a domain error. |
| `Store.create` | Insert an ORM object and return its stored fields. |
| `Store.modify` | Change existing fields atomically. |
| `Store.finish` | Persist feedback and completed flag in one transaction. |
| `Store.report` | Project distinct (ip, argument) from the prescribed outer join. |
| `Store.close` | Dispose of pooled database connections. |

### Обработка фонового задания в src/ean8_service/server.py

| ??????? | ?????????? |
|---|---|
| `process_message` | Save the PDF or failure as feedback for a background job. |
| `convert` | Launch the CLI with a temporary JSON file and a finite timeout. |

### src/ean8_service/xmlio.py

| ??????? | ?????????? |
|---|---|
| `serialize` | Encode records, lists, nulls and errors without manual escaping. |
| `parse` | Parse one flat XML record; reject nested or duplicate elements. |

### tests/test_api_mbt.py

| ??????? | ?????????? |
|---|---|
| `record` | Convert XML into a plain reference-model record. |
| `records` | Convert a collection response into reference-model records. |
| `AppModel.__init__` | Create an isolated database and independent reference model. |
| `AppModel.start` | Configure the application and client for an empty model. |
| `AppModel.transport` | Drive the real Bottle WSGI application through ApiClient. |
| `AppModel.create_account` | Create an account and return its id to a Bundle. |
| `AppModel.create_message` | Create a job and return its id to a Bundle. |
| `AppModel.modify_account` | Generate changes crossing the report time window. |
| `AppModel.modify_message` | Generate ownership and timestamp updates. |
| `AppModel.unauthorized` | Reject generated unauthorized calls. |
| `AppModel.invalid_request` | Compare malformed requests with the error model. |
| `AppModel.matches_model` | Compare visible records after every transition. |
| `AppModel.check_accounts` | Compare account reads and filters with the model. |
| `AppModel.check_messages` | Compare message and feedback reads with the model. |
| `AppModel.check_report` | Compare the report with an independent set model. |
| `AppModel.teardown` | Drain background work and remove the temporary database. |

### tests/test_barcode.py

| ??????? | ?????????? |
|---|---|
| `test_check_digits` | Compare normalization with independently calculated examples. |
| `test_invalid_codes` | Reject malformed values and incorrect check digits. |
| `test_invalid_input` | Reject unsupported input structures. |
| `test_multipage_pdf` | Open the actual PDF and verify pagination and readable digits. |

### scripts/check_style.py

| ??????? | ?????????? |
|---|---|
| `git` | Inspect this repository without changing global Git configuration. |
| `repository_errors` | Check required paths and Conventional Commits in local history. |
| `tracked_file_errors` | Reject archives, binaries, caches and editor/build output in Git. |
| `function_errors` | Count all declared arguments and physical lines including decorators. |
| `ast_errors` | Reject long functions and numeric literals anywhere in comparisons. |
| `has_numeric_literal` | Include tuple members, negative values and arithmetic operands. |
| `complexity_blocks` | Visit methods and nested closures as well as top-level functions. |
| `source_errors` | Check physical limits, comments, comparisons and Radon complexity. |
| `lint_errors` | Run PEP 8, naming, undefined-name and McCabe checks. |
| `main` | Fail the shared check command when any assignment rule is violated. |

### scripts/demo_client.py

| ??????? | ?????????? |
|---|---|
| `wait_result` | Poll a job with a deadline and return successful PDF bytes. |
| `main` | Use credentials from the same configuration as the server. |

### scripts/demo_examples.py

| ??????? | ?????????? |
|---|---|
| `main` | Save raw CLI stdout as PDF and print a readable execution log. |
