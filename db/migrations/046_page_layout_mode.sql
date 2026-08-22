-- Режим раскладки страницы дашборда.
--
--   grid — свободная сетка (как было): виджет стоит там, куда его положили
--          мышью, размер задаётся вручную. Нужен, когда человек собирает
--          страницу под конкретный рассказ.
--   flow — «поток»: место и размер считаются по ТИПУ виджета при отрисовке,
--          двигать нечего. Так устроены свёрстанные вручную отчёты: полоса
--          карточек, под ней графики, внизу таблицы во всю ширину. Страница
--          не может «поехать» и не оставляет дыр.
--
-- Умолчание grid: у существующих страниц раскладка уже расставлена руками,
-- и молча пересобирать её миграцией нельзя.
alter table dashboard_pages
    add column if not exists layout_mode text not null default 'grid';

alter table dashboard_pages
    drop constraint if exists chk_page_layout_mode;
alter table dashboard_pages
    add constraint chk_page_layout_mode check (layout_mode in ('grid', 'flow'));
