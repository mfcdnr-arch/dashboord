-- 058: строки прав (securable_objects) уходят вместе со своим объектом.
--
-- Строку заводит ТРИГГЕР при создании папки, дашборда и виджета (001_core),
-- а при удалении её не убирал никто, кроме удаления дашборда и папки руками в
-- коде. Каждая пересборка мастером удаляет виджеты — их строки оставались;
-- удаление страницы, виджета, объекта — тоже. На дев-стенде 30.09.2026 сирот
-- было 50 091 из 50 147 у виджетов, 35 816 у дашбордов, 16 240 у папок
-- (большей частью от тестов, но на боевом их растит каждая пересборка).
-- Приложение эту таблицу не читает — это мёртвый груз, растущий без предела,
-- и каскад от него шёл полным просмотром: индекса по родителю не было.
--
-- Лечим там же, где строки заводятся: триггером на удаление. Каждый объект
-- убирает СВОЮ строку. Детей, которые родителя переживают (дашборды папки,
-- если папку когда-нибудь удалят непустой), не уносим каскадом, а отцепляем:
-- внешний ключ parent_securable_id объявлен ON DELETE CASCADE, и без
-- отцепления удаление строки папки снесло бы строки живых дашбордов. Дети,
-- которые умирают вместе с родителем (виджеты дашборда), уберут себя сами
-- своим же триггером.

create index if not exists ix_securable_objects_parent
    on securable_objects (parent_securable_id) where parent_securable_id is not null;

create or replace function fn_drop_securable() returns trigger as $$
declare
    v_id uuid;
begin
    select id into v_id from securable_objects
     where object_type = TG_ARGV[0]::securable_type and object_id = old.id;
    if v_id is not null then
        update securable_objects set parent_securable_id = null where parent_securable_id = v_id;
        delete from securable_objects where id = v_id;
    end if;
    return old;
end;
$$ language plpgsql;

drop trigger if exists trg_widget_securable_drop on widgets;
create trigger trg_widget_securable_drop
    after delete on widgets
    for each row execute function fn_drop_securable('widget');

drop trigger if exists trg_dashboard_securable_drop on dashboards;
create trigger trg_dashboard_securable_drop
    after delete on dashboards
    for each row execute function fn_drop_securable('dashboard');

drop trigger if exists trg_folder_securable_drop on folders;
create trigger trg_folder_securable_drop
    after delete on folders
    for each row execute function fn_drop_securable('folder');

-- Разовая уборка накопленного. Сперва отцепляем живых детей осиротевших
-- родителей (каскад иначе унёс бы и их), затем удаляем сирот.
update securable_objects c set parent_securable_id = null
  from securable_objects p
 where c.parent_securable_id = p.id
   and (   (p.object_type = 'widget'    and not exists (select 1 from widgets    x where x.id = p.object_id))
        or (p.object_type = 'dashboard' and not exists (select 1 from dashboards x where x.id = p.object_id))
        or (p.object_type = 'folder'    and not exists (select 1 from folders    x where x.id = p.object_id)))
   and (   (c.object_type = 'widget'    and exists (select 1 from widgets    x where x.id = c.object_id))
        or (c.object_type = 'dashboard' and exists (select 1 from dashboards x where x.id = c.object_id))
        or (c.object_type = 'folder'    and exists (select 1 from folders    x where x.id = c.object_id)));

delete from securable_objects s
 where (s.object_type = 'widget'    and not exists (select 1 from widgets    x where x.id = s.object_id))
    or (s.object_type = 'dashboard' and not exists (select 1 from dashboards x where x.id = s.object_id))
    or (s.object_type = 'folder'    and not exists (select 1 from folders    x where x.id = s.object_id));

comment on function fn_drop_securable() is
    'Убирает строку прав удалённого объекта (058); живых детей отцепляет, а не уносит каскадом.';
