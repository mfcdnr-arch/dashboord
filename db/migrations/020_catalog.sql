-- 020: справочники для админ-панели и модерации (FR-8.16 / FR-8.17).
--  services            — перечень УСЛУГ организации (справочник).
--  reference_documents — служебные/справочные документы, которыми пользуется
--                        модератор при проверке дашбордов.

create table if not exists services (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    code            text not null,
    name            text not null,
    category        text,
    description     text,
    is_active       boolean not null default true,
    created_at      timestamptz not null default now(),
    unique (organization_id, code)
);
create index if not exists ix_services_org on services (organization_id, is_active);

create table if not exists reference_documents (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    title           text not null,
    description     text,
    url             text,
    created_at      timestamptz not null default now()
);
create index if not exists ix_reference_documents_org on reference_documents (organization_id);
