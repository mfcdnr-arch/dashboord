-- =========================================================
-- Система дашбордов: lifecycle документ -> метрика -> виджет -> дашборд -> публикация
-- PostgreSQL 16+. Дополняет widget_permissions_full.sql (organizations, users, roles, widgets, dashboards, folders уже созданы там)
-- =========================================================

create type document_status as enum (
    'uploaded', 'parsing', 'extracted', 'period_pending',
    'confirmed', 'mapped', 'rejected', 'released'
);
create type extraction_job_status as enum ('queued', 'running', 'succeeded', 'failed', 'needs_review');
create type dataset_release_status as enum ('draft', 'validated', 'released', 'superseded');
create type metric_status as enum ('draft', 'validated', 'approved', 'deprecated', 'archived');
create type widget_version_status as enum ('draft', 'ready', 'embedded', 'changed_after_publish', 'archived');
create type publication_request_status as enum ('pending_moderation', 'approved', 'returned_for_revision', 'cancelled');
create type publication_review_decision as enum ('approved', 'rejected', 'commented');
create type dashboard_publication_status as enum ('published', 'superseded', 'unpublished');
create type document_source_type as enum ('xlsx', 'xls', 'csv', 'pdf', 'docx');

-- ---------- 1. Документы ----------
create table documents (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    folder_id uuid references folders(id) on delete set null,
    original_filename text not null,
    source_type document_source_type not null,
    status document_status not null default 'uploaded',
    reporting_period_start date,
    reporting_period_end date,
    period_confirmed_by uuid references users(id),
    period_confirmed_at timestamptz,
    uploaded_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table document_versions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    version_no integer not null,
    storage_path text not null,
    checksum text not null,
    file_size_bytes bigint not null,
    uploaded_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (document_id, version_no)
);

-- ---------- 2. Извлечение ----------
create table extraction_jobs (
    id uuid primary key default gen_random_uuid(),
    document_version_id uuid not null references document_versions(id) on delete cascade,
    status extraction_job_status not null default 'queued',
    engine text not null default 'default-extractor',
    started_at timestamptz,
    finished_at timestamptz,
    error_message text,
    confidence_score numeric(5,4),
    created_at timestamptz not null default now()
);

create table extracted_tables (
    id uuid primary key default gen_random_uuid(),
    extraction_job_id uuid not null references extraction_jobs(id) on delete cascade,
    sheet_or_page text,
    table_index integer not null default 0,
    row_count integer,
    column_count integer,
    raw_preview jsonb,
    created_at timestamptz not null default now()
);

create table extracted_columns (
    id uuid primary key default gen_random_uuid(),
    extracted_table_id uuid not null references extracted_tables(id) on delete cascade,
    column_index integer not null,
    source_header text,
    inferred_type text,
    confidence_score numeric(5,4),
    canonical_field_code text,
    created_at timestamptz not null default now()
);

-- ---------- 3. Dataset releases ----------
create table dataset_releases (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    code text not null,
    name text not null,
    status dataset_release_status not null default 'draft',
    source_document_version_id uuid references document_versions(id),
    reporting_period_start date,
    reporting_period_end date,
    validated_by uuid references users(id),
    validated_at timestamptz,
    superseded_by_release_id uuid references dataset_releases(id),
    created_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (organization_id, code, reporting_period_start)
);

create table dataset_release_fields (
    id uuid primary key default gen_random_uuid(),
    dataset_release_id uuid not null references dataset_releases(id) on delete cascade,
    canonical_field_code text not null,
    extracted_column_id uuid references extracted_columns(id),
    unique (dataset_release_id, canonical_field_code)
);

-- ---------- 4. Метрики ----------
create table metrics (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    code text not null,
    name text not null,
    description text,
    owner_id uuid references users(id),
    created_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (organization_id, code)
);

create table metric_versions (
    id uuid primary key default gen_random_uuid(),
    metric_id uuid not null references metrics(id) on delete cascade,
    version_no integer not null,
    status metric_status not null default 'draft',
    formula_expression text not null,
    formula_ast jsonb,
    unit text,
    grain text,
    calculation_type text not null default 'aggregate',
    approved_by uuid references users(id),
    approved_at timestamptz,
    created_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (metric_id, version_no)
);

create table metric_dependencies (
    metric_version_id uuid not null references metric_versions(id) on delete cascade,
    depends_on_metric_version_id uuid references metric_versions(id) on delete cascade,
    depends_on_dataset_release_id uuid references dataset_releases(id) on delete cascade,
    check (depends_on_metric_version_id is not null or depends_on_dataset_release_id is not null)
);

create index ix_metric_dependencies_metric on metric_dependencies (metric_version_id);

-- ---------- 5. Версии виджетов ----------
create table widget_versions (
    id uuid primary key default gen_random_uuid(),
    widget_id uuid not null references widgets(id) on delete cascade,
    version_no integer not null,
    status widget_version_status not null default 'draft',
    visualization_type text not null,
    metric_version_ids uuid[] not null default '{}',
    layout jsonb not null default '{}'::jsonb,
    filters jsonb not null default '{}'::jsonb,
    created_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (widget_id, version_no)
);

-- ---------- 6. Публикация и модерация ----------
create table publication_requests (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    dashboard_version_id uuid not null references dashboard_versions(id) on delete cascade,
    status publication_request_status not null default 'pending_moderation',
    requested_by uuid not null references users(id),
    requested_at timestamptz not null default now(),
    resolved_at timestamptz
);

create table publication_reviews (
    id uuid primary key default gen_random_uuid(),
    publication_request_id uuid not null references publication_requests(id) on delete cascade,
    reviewer_id uuid not null references users(id),
    decision publication_review_decision not null,
    comment text,
    created_at timestamptz not null default now()
);

create table dashboard_publications (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    dashboard_version_id uuid not null references dashboard_versions(id) on delete cascade,
    publication_request_id uuid not null references publication_requests(id),
    status dashboard_publication_status not null default 'published',
    published_by uuid not null references users(id),
    published_at timestamptz not null default now(),
    superseded_at timestamptz
);

create unique index ux_dashboard_current_publication
    on dashboard_publications (dashboard_id)
    where status = 'published';

-- ---------- Индексы для orchestration-запросов ----------
create index ix_documents_status on documents (organization_id, status);
create index ix_extraction_jobs_status on extraction_jobs (status);
create index ix_dataset_releases_status on dataset_releases (organization_id, status);
create index ix_metric_versions_status on metric_versions (metric_id, status);
create index ix_publication_requests_status on publication_requests (status);
