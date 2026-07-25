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
  users: {
    icon: '👥',
    text: 'Управление пользователями, отделами и ролями. Жёсткого удаления нет — только блокировка, чтобы сохранить историю.',
  },
  reports: {
    icon: '📋',
    text: 'Аналитические отчёты: качество и свежесть данных, бизнес-сводка по показателям и сработавшие алерты.',
  },
  audit: {
    icon: '🔎',
    text: 'Журнал действий: кто и что менял. Доступно только администратору; выгрузка в CSV/Excel с фильтрами.',
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
      display: 'flex', alignItems: 'flex-start', gap: 10, background: '#eff4fb', border: '1px solid #d6e2f2',
      borderRadius: 10, padding: '10px 12px', marginBottom: 16, fontSize: 13, color: '#2f4666',
    }}>
      <span style={{ fontSize: 16, lineHeight: 1 }}>{hint.icon}</span>
      <span style={{ flex: 1, lineHeight: 1.45 }}>{text}</span>
      <button
        onClick={() => { localStorage.setItem(storeKey, '1'); setHidden(true) }}
        title="Больше не показывать эту подсказку"
        style={{ border: 'none', background: 'none', color: '#7089a8', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}>✕</button>
    </div>
  )
}
