# Повторение проверок

Нужны Docker Compose, Git, Bash, OpenSSL и Python 3.12. Все команды выполняются из корня репозитория, если не указано иное.

## Запуск приложения и проверка через HTTP

Исходные файлы приложения сохранены без изменений. При сборке `Dockerfile` копирует их в образ и применяет `security/patches/launch-imports.patch` только к этой копии. Правка исправляет имена импортов в `app/main.py`; SQL и денежная логика не меняются. Файл `compose.check.yml` создаёт отдельную учебную базу и Redis. Их порты не публикуются; API доступен по адресу `http://127.0.0.1:18081`, описание запросов — по адресу `http://127.0.0.1:18081/docs`.

Проверка сбрасывает данные учебной базы. Не подставляйте в её настройки рабочую PostgreSQL или Redis.

```bash
umask 077
if [ ! -f .assessment.env ]; then
  printf 'ASSESSMENT_DB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .assessment.env
fi

docker compose --env-file .assessment.env -p riskfr-http \
  -f compose.check.yml up -d --build --wait api

docker compose --env-file .assessment.env -p riskfr-http \
  -f compose.check.yml run --rm -T check \
  > security/reports/http-repeat.json
```

Новый результат сохраняется в `security/reports/http-repeat.json`. Сохранённые журналы [первой проверки](reports/http-behaviour.json) и [проверки после отделения правки](reports/http-patch-check.json) содержат по 47 запросов с совпадающими результатами. Контрольная сумма `app/main.py` в испытанных образах одинакова.

После проверки удалить временные контейнеры, данные и файл с паролем:

```bash
docker compose --env-file .assessment.env -p riskfr-http \
  -f compose.check.yml down -v
rm .assessment.env
```

## Статический анализ

Создать отдельное окружение и установить использованную версию Semgrep:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install semgrep==1.184.0
```

Проверить собственные правила и выполнить анализ семи исходных файлов:

```bash
semgrep --test --config security/rules/bank.yml \
  security/checks/rule_cases.py --metrics=off --disable-version-check
semgrep scan --config security/rules/bank.yml \
  --metrics=off --disable-version-check \
  --json --output security/reports/semgrep-repeat.json app
```

`semgrep.json` содержит первоначальный анализ исходной версии `4903ad2`. `semgrep-http.json` — сохранённый анализ испытанной копии с исправленными импортами. Команда выше создаёт новый файл `semgrep-repeat.json` и не заменяет эти результаты.

Ожидаются три успешно проверенных правила, три срабатывания в приложении и пустой массив ошибок. Два предупреждения о динамическом SQL разобраны вручную и признаны ложными срабатываниями. Файл `security/checks/rule_cases.py` содержит искусственные контрольные примеры и не входит в сканирование приложения.

Выполнить анализ с готовыми наборами:

```bash
semgrep scan --config p/python --config p/sql-injection \
  --metrics=off --disable-version-check \
  --json --output security/reports/semgrep-community-repeat.json app
```

В приложенном [отчёте](reports/semgrep-community.json) готовые наборы проверили семь файлов: загружено 185 уникальных правил, применено 151 правило Python, срабатываний и ошибок нет. Команда, версия и контрольные суммы наборов приведены в [журнале](reports/semgrep-community-run.json).

Для точного повторения с сохранёнными версиями правил:

```bash
semgrep scan --config security/rules/community/p-python.yml \
  --config security/rules/community/p-sql-injection.yml \
  --metrics=off --disable-version-check \
  --json --output security/reports/semgrep-community-snapshot-repeat.json app
```

Готовые наборы из сети могут обновляться. Для сравнения с приложенным результатом используются сохранённые файлы правил. Отсутствие их срабатываний не закрывает уязвимости, подтверждённые собственными правилами и ручными проверками.

## Проверка функций исходной версии

Проверка выполняется на исходных файлах без применения правки запуска. Создать отдельную копию текущей версии, чтобы сохранить приложенный журнал:

```bash
assessment_original=$(mktemp -d)
git worktree add --detach "$assessment_original" HEAD
(
  cd "$assessment_original"
  bash security/checks/run-isolated.sh
)
```

Результат находится в `$assessment_original/security/reports/behaviour.json`. PostgreSQL и Redis запускаются в отдельной внутренней сети без публикации портов. Для базы создаётся случайный пароль; после выполнения временные контейнеры, тома, сеть и файл окружения удаляются.

Проверяются ошибка импорта исходного приложения, принадлежность счёта, подмена пользователя, передача поисковой строки в параметры SQL, повреждённый кеш, одновременные переводы и повтор после отказа Redis. Для воспроизводимости два чтения остатка синхронизированы; отказ Redis задан проверочным объектом. SQL-запросы выполняются без изменений.

## Модель угроз

Открыть `security/model/riskfr.json` в настольном OWASP Threat Dragon 2.6.2. Проверить четыре основных элемента, шесть стрелок и три пунктирные границы. У пользователя, PostgreSQL и Redis по три угрозы, у API пять. Ещё четыре угрозы прикреплены к потокам.

На странице модели нажать `Report`, затем `PDF Report` и сохранить файл. Приложенный [PDF](reports/threat-dragon-report.pdf) выгружен этой командой: семь страниц, диаграмма, 18 угроз, из них 17 открытых и одна снижена существующей параметризацией SQL.

## Результаты для DefectDojo

- `security/reports/semgrep.json`: собственные правила, три срабатывания; тип загрузки `Semgrep JSON Report`.
- `security/reports/semgrep-community.json`: готовые правила, срабатываний нет; тот же тип загрузки, отдельное испытание.
- `security/reports/semgrep-http.json`: сохранённый анализ испытанной копии, три срабатывания; при загрузке указать применение отдельной правки импортов.
- `security/reports/manual-idor.json`: тип `Generic Findings Import`; карточку также можно создать вручную по `security/IDOR.md`.
- Полный порядок обработки приведён в разделе 6 итогового отчёта. Ручная находка IDOR и результаты собственных правил не закрываются по пустому результату готовых наборов.

## Сравнение с исходной версией

```bash
git diff 4903ad261d30bc2d1171e455f916e445a7963b4e -- \
  app requirements.txt docker-compose.yml
```

Команда не должна выводить различий: все исходные файлы приложения, зависимости и `docker-compose.yml` совпадают с выданной версией. Правка импортов находится в `security/patches/launch-imports.patch`, файлы сборки и учебного запуска добавлены отдельно.
