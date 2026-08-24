import { useEffect, useRef } from 'react'
import { buildLink, isNavigation, parseLink, sameLink, type LinkState } from './deeplink'

/**
 * Двусторонняя связь «состояние экрана ↔ адрес в браузере» (п. 6).
 *
 * **Цикла здесь нет и не может быть, и это не случайность:** `pushState` и
 * `replaceState` НЕ вызывают событие `popstate` — оно приходит только когда
 * человек нажал «назад» или «вперёд». Поэтому запись адреса не запускает
 * чтение, а чтение приводит состояние к тому, что уже в адресе, после чего
 * `sameLink` останавливает запись. Никаких флагов-предохранителей не нужно.
 *
 * **Запись в историю только при СМЕНЕ МЕСТА.** Правка периода — уточнение того
 * же места, и заводить на неё запись нельзя: пока человек набирает дату,
 * получилось бы десять записей, и кнопка «назад» перестала бы возвращать туда,
 * откуда пришли.
 */
export function useDeepLink(state: LinkState, onBack: (s: LinkState) => void): void {
  // Последнее состояние, которое мы САМИ записали в адрес. Нужно, чтобы
  // отличить смену места от правки фильтра.
  const last = useRef<LinkState>(parseLink(window.location.search))
  const onBackRef = useRef(onBack)
  onBackRef.current = onBack

  useEffect(() => {
    const current = parseLink(window.location.search)
    if (sameLink(current, state)) { last.current = state; return }
    const url = buildLink(state, window.location.pathname)
    if (isNavigation(last.current, state)) window.history.pushState(null, '', url)
    else window.history.replaceState(null, '', url)
    last.current = state
  }, [state.section, state.dashboard, state.page, state.from, state.to, state.row, state.widget]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const back = () => {
      const s = parseLink(window.location.search)
      last.current = s
      onBackRef.current(s)
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
}

/** Состояние из адреса при первом открытии — то, с чем пришли по ссылке. */
export function initialLink(): LinkState {
  return parseLink(window.location.search)
}
