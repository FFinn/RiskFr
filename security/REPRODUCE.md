# Повторение проверок

Нужны Docker Compose, Bash, OpenSSL и Python 3.12. Все команды выполняются из корня репозитория, если не указано иное.

## Запуск приложения и проверка через HTTP

Для запуска исправлены импорты `app/main.py` и добавлен корневой `Dockerfile`. Файл `compose.check.yml` создаёт отдельную учебную базу и Redis. Их порты не публикуются; API доступен по адресу `http://127.0.0.1:18081`, описание запросов — по адресу `http://127.0.0.1:18081/docs`.

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
  > security/reports/http-behaviour.json
```

Результат сохраняется в `security/reports/http-behaviour.json`. После проверки удалить временные контейнеры, данные и файл с паролем:

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
semgrep --test --config security/rules/bank.yml \
  security/checks/rule_cases.py --metrics=off --disable-version-check
semgrep scan --config security/rules/bank.yml \
  --metrics=off --disable-version-check \
  --json --output security/reports/semgrep-http.json app
```

Исходный отчёт `semgrep.json` относится к версии `4903ad2`. Повторный отчёт после исправления запуска сохраняется отдельно, в `semgrep-http.json`.

Ожидаются три успешно проверенных правила, три срабатывания в приложении и пустой массив ошибок. Два предупреждения о динамическом SQL разобраны вручную и признаны ложными срабатываниями. Файл `security/checks/rule_cases.py` содержит искусственные контрольные примеры и не входит в сканирование приложения.

## Проверка функций исходной версии

Для повторения первоначальной проверки нужна версия до исправления запуска. Изменение `57b770f` содержит исходное приложение и средства проверки:

```bash
assessment_original=$(mktemp -d)
git worktree add --detach "$assessment_original" 57b770f
(
  cd "$assessment_original"
  bash security/checks/run-isolated.sh
)
```

Результат находится в `$assessment_original/security/reports/behaviour.json`. PostgreSQL и Redis запускаются в отдельной внутренней сети без публикации портов. Для базы создаётся случайный пароль; после выполнения временные контейнеры, тома, сеть и файл окружения удаляются.

Проверяются ошибка импорта исходного приложения, принадлежность счёта, подмена пользователя, передача поисковой строки в параметры SQL, повреждённый кеш, одновременные переводы и повтор после отказа Redis. Для воспроизводимости два чтения остатка синхронизированы; отказ Redis задан проверочным объектом. SQL-запросы выполняются без изменений.

## Модель угроз

Открыть `security/model/riskfr.json` в OWASP Threat Dragon 2.6.2 через импорт локальной модели. Проверить четыре основных элемента, шесть стрелок и три пунктирные границы. У пользователя, PostgreSQL и Redis по три угрозы, у API пять. Ещё четыре угрозы прикреплены к потокам.

Открыть отчёт модели. Сводка: 18 угроз, 17 открытых, одна снижена существующей параметризацией SQL. Отчёт можно распечатать в PDF.

## Результаты для DefectDojo

- `security/reports/semgrep.json` и `semgrep-http.json`: тип загрузки `Semgrep JSON Report`. При загрузке указать соответствующую версию приложения.
- `security/reports/manual-idor.json`: тип `Generic Findings Import`; карточку также можно создать вручную по `security/IDOR.md`.
- Полный порядок обработки приведён в разделе 6 итогового отчёта. Ручная находка IDOR проверяется отдельно от повторного сканирования Semgrep.

## Сравнение с исходной версией

```bash
git diff 4903ad261d30bc2d1171e455f916e445a7963b4e -- \
  app requirements.txt docker-compose.yml
```

В приложении изменены имена импортируемой функции и моделей в `app/main.py`. Файлы сборки и учебного запуска добавлены отдельно. SQL в `app/crud.py` и `app/db.py`, зависимости и исходный `docker-compose.yml` должны совпадать с выданной версией.
