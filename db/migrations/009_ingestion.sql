-- =========================================================
-- 009 · Конвейер извлечения (ingestion)
-- Расширяем структуры извлечения под фактическое хранение данных.
--   * extracted_tables.header_rows — сколько верхних строк отнесено к шапке;
--   * extracted_tables.data        — ПОЛНАЯ сетка значений (list[list[str]]),
--                                     нужна для выпуска датасета и drill-до-первички;
--     (raw_preview остаётся усечённым предпросмотром для UI — первые 100 строк).
--   * extraction_jobs.warnings     — предупреждения парсера (кодировка, скан-PDF и т.п.).
-- Значения датасета (dataset_values) и справочник канонических полей — этап 3.2.
-- =========================================================

alter table extracted_tables
    add column if not exists header_rows integer not null default 1,
    add column if not exists data jsonb;

alter table extraction_jobs
    add column if not exists warnings jsonb;

create index if not exists ix_extraction_jobs_docver
    on extraction_jobs (document_version_id);

create index if not exists ix_extracted_tables_job
    on extracted_tables (extraction_job_id);
