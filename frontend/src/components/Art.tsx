/**
 * Декоративная графика для пустых мест — только встроенный SVG.
 *
 * Почему не картинки-файлы: система разворачивается офлайн (Astra, LAN),
 * внешних адресов нет, а растр пришлось бы рисовать под каждую из трёх тем —
 * на тёмной он смотрелся бы вырезкой. SVG на токенах темы перекрашивается сам,
 * весит доли килобайта и не добавляет ни одного сетевого запроса.
 *
 * Роль у графики служебная: показать, что пустое место — так задумано, а не
 * «страница не догрузилась». Поэтому всё приглушено и уходит на второй план,
 * а не спорит с формой входа и цифрами.
 */

/** Фон правой половины экрана входа: сетка + силуэт столбиков и линии тренда. */
export function LoginBackdrop() {
  return (
    <svg
      viewBox="0 0 600 600" width="100%" height="100%" aria-hidden="true" focusable="false"
      preserveAspectRatio="xMidYMid slice"
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
    >
      {/* сетка «миллиметровки» — намёк на аналитическую систему */}
      <g stroke="var(--border)" strokeWidth="1" opacity="0.55">
        {[60, 140, 220, 300, 380, 460, 540].map((y) => <line key={`h${y}`} x1="0" y1={y} x2="600" y2={y} />)}
        {[60, 140, 220, 300, 380, 460, 540].map((x) => <line key={`v${x}`} x1={x} y1="0" x2={x} y2="600" />)}
      </g>
      {/* столбики */}
      <g fill="var(--accent)" opacity="0.09">
        <rect x="86" y="380" width="46" height="160" rx="7" />
        <rect x="166" y="316" width="46" height="224" rx="7" />
        <rect x="246" y="348" width="46" height="192" rx="7" />
        <rect x="326" y="252" width="46" height="288" rx="7" />
        <rect x="406" y="188" width="46" height="352" rx="7" />
      </g>
      {/* линия тренда с точками */}
      <polyline
        points="109,356 189,292 269,324 349,228 429,164"
        fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
        opacity="0.16"
      />
      <g fill="var(--accent)" opacity="0.22">
        {[[109, 356], [189, 292], [269, 324], [349, 228], [429, 164]].map(([cx, cy]) => (
          <circle key={`${cx}`} cx={cx} cy={cy} r="5" />
        ))}
      </g>
    </svg>
  )
}

/** Картинка к пустому состоянию: карточки показателей, одна ещё не заполнена. */
export function EmptyKpiArt({ size = 132 }: { size?: number }) {
  return (
    <svg viewBox="0 0 200 120" width={size} height={size * 0.6} aria-hidden="true" focusable="false">
      <g fill="var(--surface-2)" stroke="var(--border)" strokeWidth="2">
        <rect x="4" y="18" width="56" height="84" rx="9" />
        <rect x="72" y="18" width="56" height="84" rx="9" />
      </g>
      {/* заполненная карточка: подпись и число */}
      <rect x="16" y="34" width="32" height="6" rx="3" fill="var(--border-strong)" />
      <rect x="16" y="52" width="26" height="14" rx="4" fill="var(--accent)" opacity="0.5" />
      <rect x="16" y="76" width="20" height="5" rx="2.5" fill="var(--border-strong)" opacity="0.7" />
      {/* вторая — ещё пустая */}
      <rect x="84" y="34" width="32" height="6" rx="3" fill="var(--border-strong)" opacity="0.6" />
      <rect x="84" y="52" width="26" height="14" rx="4" fill="var(--border-strong)" opacity="0.35" />
      {/* третья — пунктиром: место, куда добавится следующий показатель */}
      <rect
        x="140" y="18" width="56" height="84" rx="9"
        fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="6 5" opacity="0.5"
      />
      <g stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" opacity="0.6">
        <line x1="168" y1="48" x2="168" y2="72" />
        <line x1="156" y1="60" x2="180" y2="60" />
      </g>
    </svg>
  )
}
