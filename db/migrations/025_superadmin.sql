-- 025_superadmin.sql
-- Роль «Суперадминистратор» — ВЫШЕ admin в иерархии управления пользователями.
-- Суперадмин может выполнять действия над ЛЮБЫМ пользователем, включая admin
-- (блокировка/разблокировка/сброс пароля/смена ролей/удаление). Admin НЕ может
-- трогать суперадмина и не может выдавать роль superadmin (защита от эскалации).
-- Правила иерархии и «защита последнего суперадмина» — в коде (users/service.py).
--
-- Идемпотентно: роль добавляется для КАЖДОЙ организации, где её ещё нет.
-- Учётная запись суперадмина создаётся в bootstrap (ensure_seed), не здесь.

insert into roles (organization_id, code, name, is_system, can_edit_formulas, can_moderate)
select o.id, 'superadmin', 'Суперадминистратор', true, true, true
from organizations o
where not exists (
    select 1 from roles r where r.organization_id = o.id and r.code = 'superadmin'
);
