-- 018: аудит действий пишет IP запроса.
-- fn_audit_generic дополнена чтением GUC app.client_ip (её проставляет
-- db.acquire из contextvar, наполняемого ASGI-middleware). Тело функции —
-- как в 001_core.sql, добавлена только колонка ip_address.

create or replace function fn_audit_generic() returns trigger as $$
declare
    v_org_id uuid;
    v_action audit_action;
begin
    if tg_op = 'INSERT' then
        v_action := 'create';
    elsif tg_op = 'UPDATE' then
        v_action := 'update';
    elsif tg_op = 'DELETE' then
        v_action := 'delete';
    end if;

    v_org_id := coalesce(
        (case when tg_op = 'DELETE' then old.organization_id else new.organization_id end),
        null
    );

    insert into audit_log (organization_id, actor_user_id, action, entity_type, entity_id, old_data, new_data, ip_address)
    values (
        v_org_id,
        nullif(current_setting('app.current_user_id', true), '')::uuid,
        v_action,
        tg_argv[0],
        case when tg_op = 'DELETE' then old.id else new.id end,
        case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) else null end,
        case when tg_op in ('UPDATE','INSERT') then to_jsonb(new) else null end,
        nullif(current_setting('app.client_ip', true), '')
    );

    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$ language plpgsql;
