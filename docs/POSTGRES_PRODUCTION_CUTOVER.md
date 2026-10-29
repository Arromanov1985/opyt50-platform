# ОПЫТНО.РФ — production cutover SQLite → PostgreSQL

## Статус
Тестовый PostgreSQL-контур принят. Этот документ описывает безопасный порядок production-cutover.

Не выполнять merge в main, не переключать opytno-preview и не удалять SQLite без отдельного явного разрешения.

## Критическое правило порядка
opytno-preview хранит SQLite внутри непостоянного контейнера App Platform. Поэтому нельзя сначала менять ветку, сеть или переменные production-приложения: изменение конфигурации может пересоздать контейнер и уничтожить актуальный /srv/data/opyt50.db.

Правильный порядок начинается с выгрузки свежего снапшота SQLite наружу.

## Текущее состояние
- production: SQLite /srv/data/opyt50.db;
- production-приложение пока не подключено к private network PostgreSQL;
- PostgreSQL доступен в private network;
- текущая PostgreSQL содержит тестовые данные после приёмки и не является финальной production-базой;
- мигратор отказывается импортировать в непустую PostgreSQL;
- старая SQLite остаётся rollback-источником и не удаляется.

## Этап 1 — зафиксировать источник до любых изменений Timeweb
На текущем production-контейнере:

1. Ограничить новые записи на время cutover либо выбрать короткое окно без пользовательской активности.
2. Создать согласованный SQLite snapshot через SQLite backup API, включая committed WAL-данные.
3. Проверить snapshot: PRAGMA integrity_check = ok; PRAGMA foreign_key_check без ошибок; зафиксировать количество строк во всех мигрируемых таблицах.
4. Посчитать SHA-256 snapshot.
5. Выгрузить snapshot вне App Platform container и проверить SHA-256 уже у внешней копии.
6. Не продолжать, пока внешняя копия не подтверждена.

### STOP
До завершения этого этапа запрещено менять branch production, подключать production к private network, менять DATABASE_URL, перезапускать/redeploy production или удалять SQLite.

## Этап 2 — подготовить PostgreSQL target
Текущая PostgreSQL содержит тестовые записи. Финальный импорт допускается только в пустую схему.

Перед очисткой/пересозданием target требуется отдельное явное разрешение, потому что операция уничтожит тестовые данные.

После подготовки пустого target: выполнить read-only preflight; убедиться, что target содержит 0 пользовательских таблиц; проверить соединение и TLS; только после этого разрешать импорт.

## Этап 3 — финальный импорт
Использовать только свежий snapshot из Этапа 1. Мигратор должен открыть SQLite read-only, выполнить импорт одной PostgreSQL-транзакцией, сохранить ID, выставить sequence/identity, проверить counts и откатить всё при любой ошибке.

После импорта сравнить counts SQLite ↔ PostgreSQL по каждой таблице.

## Этап 4 — подготовить production-приложение
Только когда внешний SQLite snapshot проверен и финальный PostgreSQL импорт подтверждён:
1. подключить opytno-preview к той же private network, что PostgreSQL;
2. добавить production DATABASE_URL через секреты Timeweb;
3. не публиковать URL/пароль в GitHub, логах или чате;
4. развернуть проверенную runtime-ветку/релиз;
5. проверить startup logs на отсутствие DB errors.

## Этап 5 — smoke acceptance
Проверить: вход кандидата; вход работодателя; вакансии и counts; контролируемую запись; отклик; заинтересованность; приглашение; согласие; demo-знакомство; повторный restart/redeploy и сохранность записи.

## Rollback
При ошибке прекратить новые записи, вернуть предыдущую конфигурацию и использовать только отдельно сохранённый и проверенный SQLite snapshot. Не удалять PostgreSQL и не пытаться автоматически сливать записи двух БД.

## Gate перед production
- [x] PostgreSQL runtime CI green
- [x] полный сценарий PostgreSQL протестирован
- [x] persistence после restart подтверждена
- [x] timestamp compatibility исправлена
- [ ] свежий production SQLite snapshot выгружен наружу
- [ ] SHA-256 внешней копии совпадает
- [ ] production writes остановлены/окно cutover подтверждено
- [ ] PostgreSQL target очищен/пересоздан с отдельным разрешением
- [ ] свежий импорт выполнен и counts совпали
- [ ] production подключён к private network
- [ ] production DATABASE_URL настроен
- [ ] отдельное разрешение на production switch получено
- [ ] отдельное разрешение на merge в main получено
