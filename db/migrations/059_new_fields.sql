-- 059: «в форме появилась новая графа — добавить виджет?» (этап 5, решение
-- заказчика 23.09.2026).
--
-- Журнал объявленных новых граф. Графа считается новой, если у неё есть число
-- в самом свежем выпуске формы и её нет ни в одном другом выпуске того же
-- кода (правило — ingestion/new_fields.py). Журнал нужен по двум причинам:
--   1) повторная проверка (ручной выпуск, выпуск по листам, ежедневная
--      страховка воркера) не должна объявлять одну графу дважды;
--   2) удалённый выпуск уносит свои объявления граф каскадом, и без журнала
--      графа, жившая только в нём, при следующем появлении снова стала бы
--      «новой».
-- Запись есть и тогда, когда уведомления не было (форму не смотрит ни один
-- дашборд): иначе графа объявилась бы задним числом, как только дашборд
-- появится, хотя новой она к тому времени давно не будет.

create table if not exists dataset_new_fields (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    object_id       uuid references objects(id) on delete set null,
    code            text not null,
    field_code      text not null,
    field_name      text,
    release_id      uuid references dataset_releases(id) on delete set null,
    period          date,
    notice_id       uuid,
    detected_at     timestamptz not null default now(),
    unique (organization_id, code, field_code)
);

comment on table dataset_new_fields is
    'Объявленные новые графы форм: графа с числами в свежем выпуске, которой не было ни в одном другом выпуске кода';
comment on column dataset_new_fields.notice_id is
    'Уведомление, в котором графа объявлена; пусто — форму не смотрел ни один дашборд';

-- «Больше не предлагать» у подсказки дашборда: {код формы: [коды граф]}.
-- Отметка ставится человеком и только им снимается: подсказка, которая
-- возвращает отклонённые графы при каждом открытии, учит её не читать.
alter table dashboards
    add column if not exists fields_reviewed jsonb not null default '{}'::jsonb;

comment on column dashboards.fields_reviewed is
    'Графы, которые человек видел в подсказке «новые графы» и решил не добавлять: {код формы: [коды граф]}';

-- Проверка «графы нет ни в одном другом выпуске кода» идёт по всем статусам,
-- а подходящего индекса не было: только частичный уникальный по активным.
create index if not exists ix_dataset_releases_org_code
    on dataset_releases (organization_id, code);
