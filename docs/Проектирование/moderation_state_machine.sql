-- =========================================================
-- Модуль модерации дашбордов: state machine, transition rules, reason codes
-- Дополняет:
--   widget_permissions_full.sql   (dashboards, dashboard_versions, widgets, users, organizations)
--   lifecycle_schema.sql          (publication_requests, publication_reviews, dashboard_publications)
-- PostgreSQL 16+
-- Дата обновления: 2026-07-11
-- =========================================================

-- ЗАМЕЧАНИЕ ПО СОГЛАСОВАНИЮ СХЕМ:
-- В существующей схеме (lifecycle_schema.sql) уже есть publication_requests /
-- publication_reviews / dashboard_publications с enum-статусами
-- publication_request_status ('pending_moderation','approved','returned_for_revision','cancelled').
-- Этот модуль НЕ заменяет их, а расширяет до полноценной state machine:
--   dashboard_versions.status_code   -> детальный жизненный цикл ревизии (было: только publication_status на dashboards)
--   moderation_session               -> процесс проверки внутри publication_request
--   revision_transition_rule         -> декларативная матрица прав на переходы (вместо хардкода в коде)
--   moderation_reason_code           -> справочник причин возврата/отклонения
--   revision_transition_log          -> аудит по каждому переходу (дополняет publication_reviews)
--   moderation_check_result          -> снимок чек-листа проверки (структура/данные/метрики/фильтры/доступ/визуал)

-- ---------- 0. Расширение dashboard_versions статусом ревизии ----------

alter table dashboard_versions
    add column if not exists status_code text not null default 'draft',
    add column if not exists editor_touched_formula boolean not null default false,
    add column if not exists row_version integer not null default 1,
    add column if not exists parent_version_id uuid references dashboard_versions(id);

create table if not exists dashboard_revision_status (
    code            text primary key,
    label_ru        text not null,
    is_terminal     boolean not null default false,
    is_editable     boolean not null default false,
    sort_order      smallint not null
);

insert into dashboard_revision_status (code, label_ru, is_terminal, is_editable, sort_order) values
 ('draft',              'Черновик',                 false, true,  1),
 ('ready_for_review',   'Отправлен на проверку',    false, false, 2),
 ('in_review',          'На модерации',             false, false, 3),
 ('changes_requested',  'Возвращён на доработку',   false, false, 4),
 ('approved',           'Одобрен',                  false, false, 5),
 ('published',          'Опубликован',              false, false, 6),
 ('archived',           'Архив',                    true,  false, 7)
on conflict (code) do nothing;

alter table dashboard_versions
    add constraint fk_dashboard_versions_status
    foreign key (status_code) references dashboard_revision_status(code);

-- ---------- 1. Модерационная сессия (расширяет publication_requests) ----------

create table if not exists moderation_session_status (
    code            text primary key,
    label_ru        text not null,
    is_terminal     boolean not null default false
);

insert into moderation_session_status (code, label_ru, is_terminal) values
 ('not_started',                  'Не начата',                 false),
 ('claimed',                      'Взята в работу',            false),
 ('validation_failed',            'Автопроверка не пройдена',  false),
 ('under_manual_review',          'Ручная проверка',           false),
 ('waiting_for_author_response',  'Ожидание автора',           false),
 ('waiting_second_reviewer',      'Требуется вторая проверка', false),
 ('completed',                    'Завершена',                 true)
on conflict (code) do nothing;

create table if not exists moderation_session (
    id                      uuid primary key default gen_random_uuid(),
    publication_request_id  uuid not null references publication_requests(id) on delete cascade,
    dashboard_version_id    uuid not null references dashboard_versions(id) on delete cascade,
    status_code             text not null references moderation_session_status(code) default 'not_started',
    reviewer_id              uuid references users(id),
    second_reviewer_id       uuid references users(id),
    sla_due_at               timestamptz,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now()
);

create index if not exists ix_moderation_session_status on moderation_session (status_code);
create index if not exists ix_moderation_session_reviewer on moderation_session (reviewer_id);

-- ---------- 2. Справочник причин (reason codes) ----------

create table if not exists moderation_reason_code (
    code                text primary key,
    applicable_action   text not null,
    label_ru            text not null,
    severity            text not null check (severity in ('low','medium','high','critical'))
);

insert into moderation_reason_code (code, applicable_action, label_ru, severity) values
 ('DATA_SOURCE_UNAVAILABLE',        'request_changes',                                       'Источник данных недоступен',                    'high'),
 ('FORMULA_ERROR',                  'request_changes',                                       'Ошибка в формуле метрики',                       'high'),
 ('FORMULA_CYCLE_DETECTED',         'request_changes',                                       'Обнаружен цикл в расчёте',                       'critical'),
 ('EMPTY_WIDGET',                   'request_changes',                                       'Пустой виджет без данных',                       'medium'),
 ('KPI_MISMATCH_REGISTRY',          'request_changes',                                       'KPI не соответствует реестру МФЦ',               'high'),
 ('ACCESS_SCOPE_VIOLATION',         'request_changes,reject_revision',                       'Нарушение контура доступа (RLS)',                'critical'),
 ('FILTER_LOGIC_INCORRECT',         'request_changes',                                       'Некорректная логика фильтров',                   'medium'),
 ('MISSING_OWNER',                  'request_changes',                                       'Не указан владелец показателя',                  'low'),
 ('STALE_DATASET',                  'request_changes',                                       'Устаревший срез данных',                         'medium'),
 ('DUPLICATE_DASHBOARD',            'reject_revision',                                       'Дублирует существующий дашборд',                 'medium'),
 ('IRRELEVANT_CONTENT',             'reject_revision',                                       'Не соответствует назначению',                    'medium'),
 ('CONFLICT_OF_INTEREST',           'escalate_second_review',                                'Модератор редактировал формулу сам',             'high'),
 ('POLICY_REQUIRES_SECOND_REVIEW',  'escalate_second_review',                                'Требование политики о второй проверке',          'low'),
 ('POST_APPROVAL_DEFECT_FOUND',     'reopen_after_approval',                                 'Дефект найден после одобрения',                  'high'),
 ('REGULATORY_REQUIREMENT_CHANGED', 'reopen_after_approval,request_changes',                 'Изменились нормативные требования',              'high'),
 ('OTHER',                          'request_changes,reject_revision,reopen_after_approval', 'Иная причина (комментарий обязателен)',          'low')
on conflict (code) do nothing;

-- ---------- 3. Матрица допустимых переходов ----------

create table if not exists revision_transition_rule (
    id                          serial primary key,
    action_code                 text not null,
    from_status                 text not null references dashboard_revision_status(code),
    to_status                   text not null references dashboard_revision_status(code),
    required_role               text not null,
    requires_reason              boolean not null default false,
    requires_second_reviewer     boolean not null default false,
    unique (action_code, from_status, required_role)
);

insert into revision_transition_rule (action_code, from_status, to_status, required_role, requires_reason, requires_second_reviewer) values
 ('submit_for_review',        'draft',             'ready_for_review',  'author',            false, false),
 ('claim_review',             'ready_for_review',  'in_review',         'moderator',         false, false),
 ('request_changes',          'in_review',         'changes_requested', 'moderator',         true,  false),
 ('approve',                  'in_review',         'approved',          'moderator',         false, false),
 ('escalate_second_review',   'in_review',         'in_review',         'moderator',         true,  true),
 ('reject_revision',          'in_review',         'archived',          'moderator',         true,  false),
 ('reject_revision',          'in_review',         'archived',          'senior_moderator',  true,  false),
 ('second_review_approve',    'in_review',         'approved',          'senior_moderator',  false, false),
 ('second_review_return',     'in_review',         'changes_requested', 'senior_moderator',  true,  false),
 ('resubmit_revision',        'changes_requested', 'ready_for_review',  'author',            false, false),
 ('publish',                  'approved',          'published',         'publisher',         false, false),
 ('publish',                  'approved',          'published',         'org_admin',         false, false),
 ('reopen_after_approval',    'approved',          'in_review',         'senior_moderator',  true,  false),
 ('reopen_after_approval',    'approved',          'in_review',         'publisher',         true,  false),
 ('create_revision',          'published',         'draft',             'author',            false, false),
 ('archive_published',        'published',         'archived',          'publisher',         true,  false),
 ('restore_as_draft',         'archived',          'draft',             'admin',             true,  false)
on conflict do nothing;

-- ---------- 4. Лог переходов (дополняет publication_reviews) ----------

create table if not exists revision_transition_log (
    id                     bigserial primary key,
    dashboard_version_id   uuid not null references dashboard_versions(id) on delete cascade,
    moderation_session_id  uuid references moderation_session(id) on delete set null,
    action_code            text not null,
    from_status            text not null,
    to_status              text not null,
    actor_id               uuid not null references users(id),
    actor_role             text not null,
    reason_code            text references moderation_reason_code(code),
    comment                text,
    idempotency_key        uuid not null,
    created_at             timestamptz not null default now(),
    unique (idempotency_key)
);

create index if not exists ix_revision_transition_log_version on revision_transition_log (dashboard_version_id);
create index if not exists ix_revision_transition_log_actor on revision_transition_log (actor_id);

-- ---------- 5. Проверочный чек-лист (снимок на момент решения) ----------

create table if not exists moderation_check_result (
    id                     bigserial primary key,
    moderation_session_id  uuid not null references moderation_session(id) on delete cascade,
    check_block            text not null check (check_block in ('structure','data','metrics','filters','access','visual')),
    status                 text not null check (status in ('idle','running','passed','warning','failed','skipped')),
    details                text,
    created_at             timestamptz not null default now()
);

create index if not exists ix_moderation_check_result_session on moderation_check_result (moderation_session_id);
