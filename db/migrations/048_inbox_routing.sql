-- Общая зона загрузки: «Входящие» и маршрутизация файла по отпечатку формы.
--
-- До сих пор человек, сдающий недельную форму, обязан был сам выбрать объект и
-- папку — то есть знать внутреннее устройство системы. Отпечаток структуры
-- (object_layout_templates.fingerprint) уже позволяет узнать форму «в лицо»
-- после распознавания, и система может разложить файл сама.
--
-- Служебная папка «Входящие» — одна на организацию: файл попадает туда до
-- распознавания и уходит дальше, как только форма опознана. Признак хранится
-- колонкой, а не именем: имя папки человек вправе поменять.
alter table folders
    add column if not exists is_inbox boolean not null default false;

comment on column folders.is_inbox is
    'Служебная папка «Входящие» общей зоны загрузки (одна на организацию)';

create unique index if not exists uq_folders_inbox
    on folders(organization_id) where is_inbox;

-- Как файл попал в свою папку: это и есть журнал импорта. Хранить нужно именно
-- решение («опознали форму», «указал человек»), потому что по факту переноса
-- его уже не восстановить.
alter table documents
    add column if not exists routed_by text,
    add column if not exists routed_note text,
    add column if not exists routed_at timestamptz;

comment on column documents.routed_by is
    'Кто определил папку: template — опознана форма по отпечатку, manual — указал человек, null — папка выбрана при загрузке';
comment on column documents.routed_note is
    'Человеческое объяснение решения — что показывается в журнале импорта';

create index if not exists ix_documents_inbox
    on documents(organization_id, created_at desc);
