// Диалог «📦 В архив»: тема (с автоподсказкой уже использованных) + комментарий.
import { useEffect, useState, type FormEvent } from 'react'
import { archiveTopics } from '../../api/archive'
import { btn, btnGhost, dialog, input, overlay } from './shared'

export default function ArchiveDialog({ name, onClose, onSubmit }:
  { name: string; onClose: () => void; onSubmit: (topic: string, note: string) => void }) {
  const [topic, setTopic] = useState('')
  const [note, setNote] = useState('')
  const [known, setKnown] = useState<string[]>([])
  useEffect(() => { archiveTopics().then(setKnown).catch(() => {}) }, [])

  const submit = (e: FormEvent) => { e.preventDefault(); onSubmit(topic.trim(), note.trim()) }
  return (
    <div style={overlay} onClick={onClose}>
      <form style={{ ...dialog, width: 460 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <b style={{ fontSize: 16 }}>📦 Отправить в архив</b>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', margin: '8px 0 14px' }}>
          Система сохранит <b>слепок данных</b> дашборда «{name}» в папку текущего месяца — данные в
          архиве зафиксируются и не изменятся. Дашборд уйдёт из основного списка (вернуть можно из архива).
        </div>
        <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Тема (рубрика) — по ней работает поиск</label>
        <input style={{ ...input, width: '100%', boxSizing: 'border-box', marginBottom: 12 }} list="arch-topics"
          placeholder="напр. Месячная отчётность" value={topic} onChange={(e) => setTopic(e.target.value)} autoFocus />
        <datalist id="arch-topics">{known.map((t) => <option key={t} value={t} />)}</datalist>
        <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Комментарий (необязательно)</label>
        <textarea style={{ ...input, width: '100%', boxSizing: 'border-box', height: 64, paddingTop: 8, marginBottom: 16, fontFamily: 'inherit' }}
          placeholder="зачем архивируем, что важно помнить…" value={note} onChange={(e) => setNote(e.target.value)} />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" style={btnGhost} onClick={onClose}>Отмена</button>
          <button type="submit" style={btn}>Отправить в архив</button>
        </div>
      </form>
    </div>
  )
}
