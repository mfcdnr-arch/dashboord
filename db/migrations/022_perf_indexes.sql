-- 022: Индексы производительности под горячие запросы и базовые списки.
--
-- Идемпотентно (create index if not exists) — безопасно и для трекинг-раннера
-- (run-migrations.sh, одна транзакция на файл), и для повторного наката
-- apply_migrations.sh. CONCURRENTLY НЕ используем: раннер применяет файл в
-- транзакции, а concurrently в транзакции запрещён.
--
-- Закрывает запросы, которые до сих пор шли последовательным сканом:
--   • колокольчик уведомлений — на КАЖДОЙ загрузке страницы у каждого юзера;
--   • журнал аудита — базовый список и экспорт (организация + сортировка по дате);
--   • документы в папке и выбор последней версии документа (lateral join);
--   • базовые списки объектов / дашбордов / метрик по организации.

-- Уведомления: выборка получателя и счётчик непрочитанных (самый частый запрос).
create index if not exists ix_notification_recipients_user
    on notification_recipients (user_id, is_read);

-- Аудит: любой запрос журнала фильтрует организацию и сортирует по дате убыв.
-- Существующие индексы покрывают фильтры по сущности/актору, но не базовый список.
create index if not exists ix_audit_log_org_created
    on audit_log (organization_id, created_at desc);

-- Документы в папке: список сортируется по дате создания.
create index if not exists ix_documents_folder_created
    on documents (folder_id, created_at desc);

-- Последняя версия документа: lateral join в списке документов.
create index if not exists ix_document_versions_doc
    on document_versions (document_id, version_no desc);

-- Базовые списки сущностей по организации (сортировка по имени).
create index if not exists ix_objects_org_name
    on objects (organization_id, name);
create index if not exists ix_dashboards_org_name
    on dashboards (organization_id, name);
create index if not exists ix_metrics_org_name
    on metrics (organization_id, name);
