// Переместить дашборд в папку объекта («банк отделов», волна D).
import { useEffect, useState } from 'react'
import { listFolders, type Folder, type Obj } from '../../api'
import { folderLabel, folderTree } from '../../lib/folderTree'
import { btn, btnGhost, dialog, input, linkDanger, overlay, rmBtn } from './shared'

export function FolderMoveDialog({ target, objects, onClose, onMove, onClear }: {
  target: { ids: string[]; label: string; currentPath?: string | null }; objects: Obj[]; onClose: () => void
  onMove: (folderId: string) => void; onClear: () => void
}) {
  const [objId, setObjId] = useState('')
  const [folders, setFolders] = useState<Folder[]>([])
  const [folderId, setFolderId] = useState('')
  useEffect(() => {
    if (!objId) { setFolders([]); return }
    listFolders(objId).then(setFolders).catch(() => setFolders([]))
  }, [objId])
  const bulk = target.ids.length > 1
  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 420 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            📁 {bulk ? `Папка для ${target.label}` : `Папка дашборда «${target.label}»`}
          </div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 14px' }}>
          {bulk ? 'Папка будет установлена у всех выбранных дашбордов.'
            : target.currentPath ? `Сейчас в: ${target.currentPath}` : 'Сейчас без папки.'}
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          <select style={input} value={objId} onChange={(e) => { setObjId(e.target.value); setFolderId('') }}>
            <option value="">выберите объект…</option>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <select style={input} value={folderId} onChange={(e) => setFolderId(e.target.value)} disabled={!objId}>
            <option value="">выберите папку…</option>
            {folderTree(folders).map((f) => <option key={f.id} value={f.id}>{folderLabel(f)}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(bulk || target.currentPath) && <button style={linkDanger} onClick={onClear}>{bulk ? 'убрать у всех' : 'убрать из папки'}</button>}
          <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={onClose}>Отмена</button>
          <button style={btn} disabled={!folderId} onClick={() => onMove(folderId)}>Сохранить</button>
        </div>
      </div>
    </div>
  )
}
