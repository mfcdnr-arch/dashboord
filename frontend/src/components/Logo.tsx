import signUrl from '../assets/mydocs-sign.png'

// Фирменный знак «Мои Документы» (МФЦ) на белой плашке — как в брендбуке знак
// размещается на белом носителе. Белая подложка обеспечивает корректное чтение
// негативных (белых) частей знака в любой теме. Извлечён из официального брендбука.
export default function Logo({ size = 34, radius = 8, border = true }: { size?: number; radius?: number; border?: boolean }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: radius, background: '#ffffff',
      display: 'flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 auto',
      border: border ? '1px solid rgba(0,0,0,0.08)' : 'none',
    }}>
      <img src={signUrl} alt="Мои Документы" style={{ height: Math.round(size * 0.64), width: 'auto', display: 'block' }} />
    </div>
  )
}
