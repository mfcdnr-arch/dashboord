-- 036: суперадминистратор может одобрять собственную версию метрики.
--
-- Разделение обязанностей (миграция 004) запрещало самоодобрение ЖЁСТКИМ
-- CHECK-ограничением: approved_by <> created_by. Для владельца системы это
-- тупик — пока в организации нет второго сотрудника с правом модерации,
-- метрику невозможно довести до статуса «одобрена» вообще.
--
-- Ограничение не снимается, а уточняется: запрет остаётся для всех ролей,
-- кроме superadmin. CHECK так не умеет (нужен запрос к user_roles), поэтому
-- он заменён триггером. Уровень защиты в БД сохраняется: даже если проверка
-- в приложении будет обойдена, обычный модератор своё не одобрит.
--
-- Самоодобрение при этом не замалчивается: created_by = approved_by в строке
-- остаётся признаком того, что версию одобрил её же автор.

alter table metric_versions drop constraint if exists chk_metric_no_self_approve;

create or replace function fn_metric_no_self_approve() returns trigger as $$
begin
    if new.approved_by is not null and new.approved_by = new.created_by then
        if not exists (
            select 1 from user_roles ur
            join roles r on r.id = ur.role_id
            where ur.user_id = new.approved_by and r.code = 'superadmin'
        ) then
            -- 23514 = check_violation: код тот же, что давало прежнее ограничение
            raise exception 'Нельзя одобрять собственную версию метрики (конфликт интересов)'
                using errcode = '23514';
        end if;
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_metric_no_self_approve on metric_versions;
create trigger trg_metric_no_self_approve
    before insert or update of approved_by, created_by on metric_versions
    for each row execute function fn_metric_no_self_approve();
