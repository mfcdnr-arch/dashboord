import AppealsPanel from './AppealsPanel'

// Раздел «Обращения» (staff: admin/moderator/senior_moderator/superadmin) —
// все заявки организации. Личные обращения пользователя — в «Кабинете».
export default function AppealsPage({ initialAppealId }: { initialAppealId?: string | null }) {
  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Обращения</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        Вопросы и проблемы, которые пользователи направили администратору или модератору.
      </div>
      <AppealsPanel scope="all" initialAppealId={initialAppealId} />
    </div>
  )
}
