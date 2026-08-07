import { useEffect, useState } from 'react'

// Онбординг-подсказка: короткий гасимый баннер вверху раздела. Текст зависит от
// роли (руководитель admin/moderator видит расширенную подсказку). Закрытие
// запоминается на пользователя и раздел (localStorage) — повторно не мешает.

type Hint = { icon: string; text: string; managerText?: string }

const HINTS: Record<string, Hint> = {
  home: {
    icon: '🏠',
    text: 'Витрина ключевых показателей: сводка, свежесть данных и уведомления в колокольчике.',
    managerText: 'Набор KPI на витрине настраивается кнопкой «Настроить».',
  },
  objects: {
    icon: '🗂️',
    text: 'Объекты → папки → документы. Данные попадают в систему через загрузку и распознавание отчётов.',
    managerText: 'Кнопка «🔐 Доступ к строкам» ограничивает видимость строк данных по подразделению.',
  },
  metrics: {
    icon: '📐',
    text: 'Показатели с прозрачными формулами. Откройте метрику — увидите расчёт, источники и предпросмотр на данных.',
    managerText: 'Новую версию формулы одобряет другой сотрудник (разделение обязанностей).',
  },
  dashboards: {
    icon: '📊',
    text: 'Дашборды собираются из виджетов. Значок «i» у виджета поясняет, что он показывает; «🔍 подробнее» раскрывает расчёт.',
    managerText: 'Вы можете создавать дашборды, задавать доступ (в т.ч. по отдельным виджетам) и вести обсуждение.',
  },
  showcases: {
    icon: '📺',
    text: 'Витрина — подборка из нескольких ЦЕЛЫХ дашбордов на одном экране: общий обзор для руководителя или показ на большом мониторе. Открывается на вкладке «👁 Просмотр». Не путать с режимом «📺 Витрина» внутри дашборда — тот по очереди листает страницы одного дашборда.',
    managerText: 'Состав набирается на вкладке «Состав»: добавьте дашборды и расставьте порядок перетаскиванием за ⠿. Каждый видит в витрине только те дашборды, к которым у него есть доступ.',
  },
  archive: {
    icon: '📦',
    text: 'Архив дашбордов по месяцам: слепки «как было на момент архивации» — данные в них зафиксированы и не меняются. Поиск по названию и теме.',
    managerText: 'Кнопка «📦 В архив» — на дашборде; «🔑 Доступ к архиву» выдаёт раздел обычным пользователям; «📅 автослепок» — ежемесячная автоархивация.',
  },
  users: {
    icon: '👥',
    text: 'Управление пользователями, отделами и ролями. Для тех, кто что-то создавал, надёжнее блокировка (сохраняет историю); жёсткое удаление доступно только для «чистых» учёток. Роль «Суперадминистратор» — управление любым пользователем, включая администраторов.',
  },
  reports: {
    icon: '📋',
    text: 'Аналитические отчёты: качество и свежесть данных, бизнес-сводка по показателям и сработавшие алерты.',
  },
  audit: {
    icon: '🔎',
    text: 'Журнал действий: кто и что менял. Доступно только администратору; выгрузка в CSV/Excel с фильтрами.',
  },
  settings: {
    icon: '⚙️',
    text: 'Параметры системы: свежесть данных и срок их хранения, защита входа, границы нагрузки, бэкап и автоархив. Всё меняется здесь, править файлы на сервере не нужно.',
  },
  profile: {
    icon: '👤',
    text: 'Ваши данные, роли и история собственных действий. Вкладка «💬 Мои обращения» — переписка с администратором: там же можно задать вопрос или сообщить о проблеме.',
  },
}

function isManager(roles: string[]): boolean {
  return roles.some((r) => ['admin', 'moderator', 'senior_moderator'].includes(r))
}

export default function OnboardingHint({ section, roles, userKey }: { section: string; roles: string[]; userKey: string }) {
  const hint = HINTS[section]
  const storeKey = `onbd:${userKey}:${section}`
  const [hidden, setHidden] = useState(true)

  useEffect(() => {
    setHidden(localStorage.getItem(storeKey) === '1')
  }, [storeKey])

  if (!hint || hidden) return null
  const text = hint.text + (hint.managerText && isManager(roles) ? ' ' + hint.managerText : '')

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10, background: 'var(--accent-weak-bg)', border: '1px solid var(--border)',
      borderRadius: 10, padding: '10px 12px', marginBottom: 16, fontSize: 13, color: 'var(--text-2)',
    }}>
      <span style={{ fontSize: 16, lineHeight: 1 }}>{hint.icon}</span>
      <span style={{ flex: 1, lineHeight: 1.45 }}>{text}</span>
      <button
        onClick={() => { localStorage.setItem(storeKey, '1'); setHidden(true) }}
        title="Больше не показывать эту подсказку"
        style={{ border: 'none', background: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}>✕</button>
    </div>
  )
}
