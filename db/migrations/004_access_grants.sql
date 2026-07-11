-- =========================================================
-- RBAC visibility schema v2
-- Изменения относительно rbac_visibility_schema.sql (v1):
--   1) moderator терь тоже редактирует формулы (can_edit_formulas = true)
--   2) dashboard_access_grants расширен до detail-level: дашборд целиком или отдельные виджеты/drill-down
-- =========================================================

-- ---------- 1. Модератор получает право редактировать формулы ----------
update roles set can_edit_formulas = true where code = 'moderator';

-- теперь оба роли с правом на редактирование должны отражаться в metric_versions.created_by/approved_by
-- важно: approve все равно делает только admin или moderator с can_moderate=true —
-- если модератор сам создал версию формулы, он не может сам ее же approve (segregation of duties)
alter table metric_versions
    add constraint chk_metric_no_self_approve
    check (approved_by is null or approved_by <> created_by);

-- ---------- 2. Detail-level гранты: дашборд целиком или конкретный виджет ----------
create type access_grant_scope as enum ('dashboard', 'widget');

-- заменяет таблицу dashboard_access_grants из v1 (расширяем колонками)
drop table if exists dashboard_access_grants;

create table access_grants (
    id uuid primary key default gen_random_uuid(),
    scope access_grant_scope not null default 'dashboard',
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    widget_id uuid references widgets(id) on delete cascade,   -- null при scope='dashboard'
    grantee_type text not null check (grantee_type in ('role', 'user')),
    role_id uuid references roles(id),
    user_id uuid references users(id),
    granted_by uuid not null references users(id),
    granted_at timestamptz not null default now(),
    check (
        (grantee_type = 'role' and role_id is not null and user_id is null) or
        (grantee_type = 'user' and user_id is not null and role_id is null)
    ),
    check (
        (scope = 'dashboard' and widget_id is null) or
        (scope = 'widget' and widget_id is not null)
    )
);

create index ix_access_grants_dashboard on access_grants (dashboard_id, scope);
create index ix_access_grants_widget on access_grants (widget_id) where widget_id is not null;
create index ix_access_grants_user on access_grants (user_id) where user_id is not null;
create index ix_access_grants_role on access_grants (role_id) where role_id is not null;

-- гарантия: widget-грант должен ссылаться на виджет, который действительно привязан к этому дашборду
-- (проверяется в коде сервиса через dashboard_versions -> widget_versions -> widget_id,
--  так как widget может быть переиспользован в нескольких дашбордах)

-- Логика разрешения видимости (реализуется в AccessService, не в SQL-правах):
--   1. admin и moderator видят всё без explicit grant
--   2. дашборд виден, если есть access_grants(scope='dashboard') на роль или на user_id
--   3. если дашборд виден, но есть активные widget-level гранты для этого дашборда —
--      то пользователь видит только те widget_id, на которые есть грант (whitelist)
--   4. если для дашборда нет ни одного widget-level гранта — видны все виджеты (fallback к dashboard-level)
