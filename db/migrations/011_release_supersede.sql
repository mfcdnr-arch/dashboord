-- =========================================================
-- 011 · Уникальность выпуска датасета с учётом supersede
-- Проблема: жёсткий unique(org, code, period) не давал заместить выпуск —
-- новый выпуск за тот же период конфликтовал со старым до его архивации.
-- Решение: уникальность только среди АКТИВНЫХ выпусков (status <> 'superseded').
-- Замещённые (superseded) сосуществуют как история.
-- =========================================================

alter table dataset_releases
    drop constraint if exists dataset_releases_organization_id_code_reporting_period_star_key;

create unique index if not exists uq_dataset_releases_active
    on dataset_releases (organization_id, code, reporting_period_start)
    where status <> 'superseded';
