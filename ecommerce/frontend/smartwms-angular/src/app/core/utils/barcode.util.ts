/**
 * Generador determinista de códigos de barras Code 128 (Subconjunto B) en SVG Data URI.
 * Soporta todo el rango ASCII imprimible (32..126), ideal para SKUs alfanuméricos.
 */

const CODE128_PATTERNS: readonly string[] = [
  '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
  '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
  '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
  '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
  '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
  '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
  '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
  '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
  '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
];

const START_CODE_B = 104;
const STOP_CODE = 106;

/**
 * Genera un Data URI SVG para un código de barras Code 128B limpio y escaneable.
 */
export function generateCode128SvgDataUri(rawValue: string): string {
  const clean = (rawValue || '').trim();
  if (!clean) return '';

  const codes: number[] = [START_CODE_B];
  let checksum = START_CODE_B;

  for (let i = 0; i < clean.length; i++) {
    const charCode = clean.charCodeAt(i);
    // Code 128B admite ASCII 32..126; cualquier otro carácter se normaliza a '?'
    const val = charCode >= 32 && charCode <= 126 ? charCode - 32 : 31;
    codes.push(val);
    checksum += (i + 1) * val;
  }

  codes.push(checksum % 103);
  codes.push(STOP_CODE);

  const moduleWidth = 2;
  const barHeight = 72;
  const quietModules = 10;
  const verticalPad = 10;

  let cursorModules = quietModules;
  const bars: string[] = [];

  for (const code of codes) {
    const pattern = CODE128_PATTERNS[code];
    for (let j = 0; j < pattern.length; j++) {
      const widthModules = Number(pattern[j]);
      if (j % 2 === 0) {
        bars.push(
          `<rect x="${cursorModules * moduleWidth}" y="${verticalPad}" width="${widthModules * moduleWidth}" height="${barHeight}" fill="#000000"/>`
        );
      }
      cursorModules += widthModules;
    }
  }

  const totalWidth = (cursorModules + quietModules) * moduleWidth;
  const totalHeight = barHeight + verticalPad * 2;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="${totalHeight}" viewBox="0 0 ${totalWidth} ${totalHeight}" shape-rendering="crispEdges">` +
    `<rect width="100%" height="100%" fill="#ffffff"/>` +
    bars.join('') +
    `</svg>`;

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
