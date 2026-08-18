-- Раздел пользователя: инструкции, объявления администратора и признак
-- «показывать раздел Руководителю».
--
-- Зачем: обычный пользователь до сих пор видел список отчётов и свой кабинет —
-- и всё. Ни где прочитать, как пользоваться системой, ни как узнать о работах
-- на сервере или новом отчёте. Инструкции и объявления закрывают именно это.

-- Инструкции. Текст пишется прямо в системе, файл (готовое руководство .docx
-- или .pdf) можно приложить — у заказчика они уже есть, перенабирать их незачем.
create table if not exists instructions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  -- Раздел для группировки в списке («Начало работы», «Отчёты», «Загрузка данных»).
  section text,
  title text not null,
  body text,
  -- Приложенный файл: ключ в MinIO, имя и размер для показа без обращения к хранилищу.
  file_path text,
  file_name text,
  file_size_bytes bigint,
  -- Порядок внутри раздела: инструкции читают по шагам, алфавит тут не помощник.
  position integer not null default 0,
  -- Черновик не виден пользователям: администратор пишет постепенно.
  is_published boolean not null default true,
  created_by uuid not null references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ix_instructions_org on instructions (organization_id, section, position, created_at);

-- Кто что прочитал: нужно для отметки «новое». Читатель не должен каждый раз
-- просматривать весь список, чтобы понять, появилось ли что-то с прошлого раза.
create table if not exists instruction_reads (
  instruction_id uuid not null references instructions(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  read_at timestamptz not null default now(),
  primary key (instruction_id, user_id)
);

-- Объявления администратора: видны всем на главной.
--
-- Срок показа и признак «важное» — не украшение: без срока главная за месяц
-- зарастает старыми сообщениями, и их перестают читать вообще, а тогда
-- сообщение о реальной проблеме тоже пройдёт мимо.
create table if not exists announcements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  title text not null,
  body text not null,
  important boolean not null default false,
  starts_at timestamptz not null default now(),
  -- null — бессрочно (например, режим работы поддержки).
  ends_at timestamptz,
  is_active boolean not null default true,
  created_by uuid not null references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ix_announcements_active
  on announcements (organization_id, is_active, starts_at desc);

-- Раздел «Руководителю» — не всем.
--
-- Он показывает подборку отчётов для руководства, и обычному сотруднику там
-- делать нечего. Решение заказчика: галочка у сотрудника, а не отдельная роль —
-- роль пришлось бы выдавать вдобавок к существующим и учитывать в проверках прав.
-- По умолчанию выключена: право показывать что-то руководству выдаётся осознанно.
alter table users add column if not exists show_featured boolean not null default false;
