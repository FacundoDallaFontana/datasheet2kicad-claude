# dsgen: del datasheet PDF al símbolo y footprint de KiCad

Idea inspirada en scheMAGIC: le das el **PDF del datasheet** y el **part number completo** y
obtenés el `.kicad_sym` y el `.kicad_mod`.

- **Lectura del PDF:** Claude Code en modo headless (`claude -p`), guiado por
  [`prompts/extract_component.md`](prompts/extract_component.md). Usa tu suscripción de Claude
  Code, no necesitás API key.
- **Símbolo:** [KiPart](https://github.com/devbisme/kipart).
- **Footprint:** los generadores IPC-7351 oficiales de
  [kicad-footprint-generator](https://gitlab.com/kicad/libraries/kicad-footprint-generator)
  (KicadModTree). Si en tu instalación de KiCad ya hay un footprint oficial con la misma geometría
  de pads, se usa ese.

## Instalación

Requisitos: Python 3.11+, git, KiCad 8/9/10 y Claude Code (`claude`) en el PATH.

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

KiCad se detecta solo (`C:\Program Files\KiCad\<ver>`, `D:\kicad9.0`, …). Si no lo encuentra,
definí `DSGEN_KICAD_DIR` o agregá `"kicad_dir"` en `~/.dsgen/config.json`.

## Uso

```powershell
.venv/Scripts/python -m dsgen            # GUI
.venv/Scripts/python -m dsgen datasheet.pdf --part TPS62130RGTR -o out/
.venv/Scripts/python -m dsgen --from-json out/TPS62130RGT.component.json -o out/   # sin IA
```

En la GUI el flujo es:
1. Elegís el PDF, el part number y la carpeta de salida, y hacés clic en **Extraer con IA**.
2. Revisás y corregís los pines, el package y la info. Los problemas aparecen en rojo, y hay
   botones para abrir el PDF en la página de donde salió cada dato.
3. Hacés clic en **Generar** y ves el preview del símbolo y del footprint.

Salida en la carpeta elegida:
- `<lib>.kicad_sym`: librería de símbolos. Cada parte nueva se agrega; si ya existía, se
  reemplaza.
- `<lib>.pretty/`: footprints generados. Solo se crea cuando no hay uno oficial equivalente.
- `<parte>.component.json`: los datos extraídos. Se pueden editar y re-generar sin llamar a la IA.

Tenés que agregar la `.kicad_sym` y la `.pretty` a las tablas de librerías de KiCad.

## Consumo

Cada llamada a Claude (incluidos reintentos y errores) se registra en `~/.dsgen/usage.csv`:
fecha, PDF, part number, modelo, turnos, duración, tokens (entrada, salida, caché) y costo
equivalente en USD. Las extracciones que salen de la caché no consumen y no se registran.

- La GUI muestra el acumulado abajo de todo; "Ver detalle (CSV)" abre el archivo.
- Por consola: `.venv/Scripts/python -m dsgen --usage`

Con la suscripción de Claude Code el costo no se cobra aparte, pero descuenta de tu límite de uso.

## Cómo funciona

```
PDF + part number
 → preprocess.py   páginas candidatas (ordering / pinout / package) con PyMuPDF
 → cache.py        si ya se extrajo ese PDF + part number, no se llama a Claude
 → extractor.py    claude -p --json-schema … (salida validada con schema.py)
 → validate.py     chequeos de sanidad; si hay errores, 1 reintento con el detalle
 → [GUI: revisión]
 → footprint_gen.py  genera con el generador IPC → compara pads con la librería oficial
                     (kicad_lib.py) → usa el oficial o guarda el generado
 → symbol_gen.py     KiPart (con la propiedad Footprint apuntando al elegido)
```

Familias soportadas para generar footprint:
- `gullwing`: SOIC, SSOP, TSSOP, MSOP, QFP y SOT-23.
- `nolead`: QFN, DFN y SON, con EP.
- `tab`: SOT-223, TO-252 y TO-263.

Para el resto (`other`) se genera solo el símbolo.

Para ajustar lo que la IA busca en el PDF, editá `prompts/extract_component.md` y subí
`PROMPT_VERSION` en `dsgen/cache.py` para invalidar la caché.

## Tests

```powershell
.venv/Scripts/python -m pytest
```

Los tests no usan IA. Generan packages JEDEC conocidos, verifican que coincidan con los
footprints oficiales de KiCad y que `kicad-cli` pueda abrir todos los archivos generados.

## Notas

- Modelo: `sonnet` por defecto. En las pruebas, `haiku` extrajo bien los pines pero leyó mal
  las cotas del dibujo mecánico, además de tardar más.
- kicad-footprint-generator escribe en formato KiCad 10. Si tu KiCad es 8 o 9, el archivo se
  convierte automáticamente (`kicad_env.downgrade_footprint`).
- En la familia tab, el land pattern se calcula con IPC-7351B nominal. Los footprints oficiales
  de SOT-223/DPAK están hechos a mano, así que el match con ellos es más tolerante (±0.3 mm).
