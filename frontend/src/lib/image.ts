// Подготовка картинки-виджета к встраиванию в дашборд как data-URI.
//
// Зачем: картинка хранится прямо в config виджета (работает офлайн на Astra,
// без отдельного маршрута отдачи файлов). Чтобы это не раздувало JSON виджета
// и версии дашборда, крупные изображения СЖИМАЮТСЯ на клиенте — даунскейл до
// разумной стороны + пере-кодирование. Итог — небольшой data-URI (обычно
// десятки КБ) независимо от размера исходника.

export const IMG_MAX_INPUT_MB = 12   // предел сырого файла (до сжатия)
export const IMG_MAX_DIM = 512       // макс. сторона после даунскейла, px
const SKIP_COMPRESS_BYTES = 48 * 1024 // маленькие лого не пересжимаем (чёткость)
const JPEG_QUALITY = 0.85

/** Новые размеры с сохранением пропорций, чтобы бОльшая сторона ≤ max. */
export function scaledDimensions(w: number, h: number, max: number): { w: number; h: number } {
  const longest = Math.max(w, h)
  if (longest <= max || longest === 0) return { w, h }
  const k = max / longest
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) }
}

/** Примерный размер data-URI в байтах (base64 ≈ 4/3 от бинарного). */
export function dataUriBytes(dataUri: string): number {
  const comma = dataUri.indexOf(',')
  const b64 = comma >= 0 ? dataUri.slice(comma + 1) : dataUri
  return Math.round(b64.length * 0.75)
}

function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result || ''))
    r.onerror = () => reject(new Error('Не удалось прочитать файл'))
    r.readAsDataURL(file)
  })
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Не удалось декодировать изображение'))
    img.src = src
  })
}

/**
 * Файл → сжатый data-URI. SVG (вектор) и небольшие растровые лого встраиваются
 * как есть. Крупные растровые уменьшаются до IMG_MAX_DIM и пере-кодируются:
 * PNG/GIF (могут иметь прозрачность) — в PNG; фото — в JPEG. Если PNG вышел
 * тяжелее JPEG — берём JPEG (для непрозрачных так меньше).
 */
export async function fileToEmbeddableDataUri(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error('Это не изображение')
  if (file.size > IMG_MAX_INPUT_MB * 1024 * 1024) {
    throw new Error(`Слишком большой файл (${Math.round(file.size / 1024 / 1024)} МБ). Максимум ${IMG_MAX_INPUT_MB} МБ.`)
  }
  // Вектор — уже мал и масштабируется без потерь.
  if (file.type === 'image/svg+xml') return readAsDataUrl(file)
  const srcDataUrl = await readAsDataUrl(file)
  // Небольшие лого не пересжимаем — сохраняем чёткость.
  if (file.size <= SKIP_COMPRESS_BYTES) return srcDataUrl

  const img = await loadImage(srcDataUrl)
  const { w, h } = scaledDimensions(img.naturalWidth || img.width, img.naturalHeight || img.height, IMG_MAX_DIM)
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return srcDataUrl // на всякий случай — без canvas отдаём как есть
  ctx.drawImage(img, 0, 0, w, h)

  // Форматы, которые МОГУТ иметь прозрачность. Реальную прозрачность проверяем
  // по пикселям: если альфа есть — сохраняем PNG (JPEG её бы уничтожил); если
  // изображение фактически непрозрачно — берём меньший из JPEG/PNG.
  const mayHaveAlpha = file.type === 'image/png' || file.type === 'image/gif' || file.type === 'image/webp'
  const transparent = mayHaveAlpha && hasTransparency(ctx, w, h)
  let out: string
  if (transparent) {
    out = canvas.toDataURL('image/png')            // прозрачность сохраняется
  } else {
    const jpeg = canvas.toDataURL('image/jpeg', JPEG_QUALITY)
    const png = canvas.toDataURL('image/png')
    out = jpeg.length <= png.length ? jpeg : png   // непрозрачное — берём компактнее
  }
  // Если по какой-то причине сжатие не помогло — берём меньший вариант.
  return out.length < srcDataUrl.length ? out : srcDataUrl
}

/** Есть ли в изображении хоть один полупрозрачный пиксель (альфа < 255). */
function hasTransparency(ctx: CanvasRenderingContext2D, w: number, h: number): boolean {
  try {
    const { data } = ctx.getImageData(0, 0, w, h)
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] < 255) return true
    }
  } catch {
    return true // не смогли проверить — консервативно считаем прозрачным (сохраним PNG)
  }
  return false
}
