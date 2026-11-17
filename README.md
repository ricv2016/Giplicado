# Giplicado

Aplicación de escritorio (Windows) para encontrar **fotos, audio y video duplicados** y
**renombrar archivos** uno por uno o por lote, con **reproductor integrado** para revisar
cada archivo antes de eliminarlo o renombrarlo.

## Tecnología (todo gratis / código abierto)
| Componente | Uso |
|---|---|
| Python 3.13 | Lenguaje |
| PySide6 (Qt, LGPL) | Interfaz gráfica |
| Qt Multimedia (incluido en PySide6, motor FFmpeg) | Reproductor de audio y video |
| hashlib BLAKE2b (incluido en Python) | Duplicados exactos |
| NumPy | Fotos parecidas (hash perceptual pHash, compatible con ImageHash) |
| PyAV (FFmpeg, LGPL) | Videos parecidos (lectura de cuadros) |
| Chromaprint `fpcalc` (LGPL) | Misma canción en otro formato (huella acústica) |
| Pillow | Lectura de fotos y fecha EXIF |
| Send2Trash | Enviar a la Papelera de forma segura |

## Instalar y ejecutar
```
python -m pip install -r requirements.txt
python main.py
```

### Activar la comparación de audio
1. Descarga Chromaprint para Windows: https://acoustid.org/chromaprint
   (archivo `chromaprint-fpcalc-1.5.1-windows-x86_64.zip`).
2. Copia `fpcalc.exe` en la carpeta `tools\` de este proyecto.

## Modos de búsqueda
| Modo | Qué encuentra | Ajuste |
|---|---|---|
| Contenido idéntico | Copias exactas byte a byte con cualquier nombre | — |
| Fotos parecidas | La misma foto redimensionada, recomprimida (WhatsApp), en otro formato | Tolerancia 0–16 (recomendado 6) |
| Misma canción | MP3 / FLAC / M4A / WAV… de la misma grabación | Coincidencia mínima % (recomendado 80) |
| Videos parecidos | El mismo video en otra resolución, formato o calidad | Tolerancia 0–24 (recomendado 10) |

En los modos "parecidos" la app propone conservar la copia de **mejor calidad**
(más resolución o más kbps). Revisa siempre en el reproductor antes de borrar.

## Caché de análisis
Las huellas calculadas se guardan en `%LOCALAPPDATA%\Giplicado\cache.db`; repetir una búsqueda
solo analiza los archivos nuevos o modificados. Se puede borrar en *Herramientas → Borrar caché*.

## Tema
*Ver → Tema*: según Windows, claro u oscuro.

## Reproductor
Panel a la derecha en ambas pestañas: muestra las fotos y reproduce el audio y el video
(play/pausa, barra de posición, volumen, silencio, Ctrl+Espacio, auto-reproducir).
Antes de borrar, mover o renombrar suelta el archivo para que Windows no lo bloquee.

## Renombrado
Etiquetas: `{nombre}` `{n}` `{fecha}` `{hora}` `{carpeta}` `{tipo}` · buscar/reemplazar (regex) ·
mayúsculas · numeración · detección de conflictos · edición manual (doble clic) · **Deshacer**.

## Pruebas
```
python -m unittest tests/test_core.py tests/test_similar.py tests/test_updater.py tests/test_v03.py -v
```

## Crear el ejecutable (.exe)
```
python -m pip install pyinstaller
python -m PyInstaller giplicado.spec --noconfirm
```
Resultado: `dist\Giplicado\Giplicado.exe`. Para distribuirlo, comprime la carpeta
`dist\Giplicado` completa (el .exe necesita la carpeta `_internal` que está a su lado).

## Crear el instalador
Requiere Inno Setup (gratuito): https://jrsoftware.org/isdl.php
```
"C:\Program Files\Inno Setup 7\ISCC.exe" installer\giplicado.iss
```
Resultado: `dist\Giplicado-0.1.0-instalador.exe` (un solo archivo, ~50 MB). Incluye accesos
directos en el menú Inicio y el escritorio, y desinstalación desde Configuración de Windows.
Al publicar una versión nueva, cambia `AppVersion` en `installer\giplicado.iss` y
`__version__` en `giplicado\__init__.py`.

## Licencia
Giplicado se distribuye bajo la licencia **MIT** (ver `LICENSE`).
El instalador incluye `fpcalc` de [Chromaprint](https://acoustid.org/chromaprint) (LGPL 2.1) y
las bibliotecas de Qt / PySide6 (LGPL 3), cada una bajo su propia licencia.

## Publicar una nueva versión
1. Cambia `__version__` en `giplicado/__init__.py` (ej. `0.2.0`) y haz commit.
2. `git tag v0.2.0` y `git push origin main v0.2.0`
3. GitHub Actions compila y publica el instalador; las copias instaladas de Giplicado
   lo detectarán y ofrecerán actualizarse.
