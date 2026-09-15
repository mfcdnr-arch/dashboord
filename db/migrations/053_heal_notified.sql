-- Отметка «об этой починке уже сообщили».
--
-- Хостовой сторож (worker-guard.sh) поднимает упавший фоновый воркер и пишет
-- запись сюда. Рассылает уведомление НЕ он: пока воркер мёртв, рассылать
-- некому — это делает сторожевой cron уже после оживления. Значит нужна
-- отметка, иначе одно падение рассылалось бы каждые 10 минут бесконечно.
alter table system_heal_log add column if not exists notified_at timestamptz;

-- Выбираются только неуведомлённые записи о воркере, поэтому индекс частичный.
create index if not exists ix_system_heal_log_unnotified
    on system_heal_log (created_at) where notified_at is null;
