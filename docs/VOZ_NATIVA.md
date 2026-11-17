# IRIS 0.2: interacción por voz

El producto es un asistente que escucha y habla desde la PC. Durante el armado físico,
una ventana opcional muestra sus ojos, estados y transcripciones. La terminal sólo
muestra diagnóstico. La ventana no es necesaria para conversar y se puede retirar al
conectar los ojos físicos.

## Visualización temporal y paso al cuerpo físico

`--monitor` abre una ventana nativa de escritorio con ojos animados, estado de audio,
trabajos en curso y registro de la conversación real de esa sesión. No tiene botones
para pedir tareas: se usa la voz. La ventana informa si el micrófono está activo.
Cerrar la ventana termina la sesión y libera el audio; también se puede usar Ctrl+C.

```powershell
.\.venv\Scripts\python.exe -m iris --demo --monitor
```

Para revisar sólo lo visual, sin abrir micrófono/parlante ni llamar APIs:

```powershell
.\.venv\Scripts\python.exe -m iris --preview
```

`--preview` es una escena ilustrativa identificada como simulación, sin resultados
de investigación. Para probar voz real local, usar `--demo --monitor`.

La ventana consume `Feedback`, que publica instantáneas inmutables de estado. Ese
canal emite expresiones `idle`, `listening`, `thinking` y `speaking`, compatibles con
los nombres de estados por Serial del firmware publicado. Una investigación sigue
figurando entre las tareas mientras los ojos reaccionan a la escucha o la voz.
Un fallo de un observador no debe cortar la conversación.

```text
Micrófono / salida PC → conversación → gestor → proveedores y herramientas
                              ↓
                           Feedback
                              ↓
                      Monitor de escritorio

Después: transporte de audio del robot + adaptador Feedback → OLED / expresiones
```

Al montar el cuerpo, se puede ejecutar sin `--monitor` y sustituir el consumidor
visual mediante `Feedback.subscribe()`. El adaptador no toma decisiones ni ejecuta
herramientas. El audio de la PC está concentrado en `AudioDevice`; el transporte
físico deberá respetar la captura y reproducción PCM, y adaptar los 16 kHz actuales
del firmware a los 24 kHz de la sesión cloud.

**No hay aún conexión Serial/MQTT ni transporte de audio del ESP32.** La animación
autónoma y el VAD del sketch deben coordinarse con el estado enviado por el cerebro,
para que no lo sobrescriban. El futuro cuerpo usa estas señales y la conversación
existente; la ventana temporal puede desaparecer sin cambiar los proveedores ni
las herramientas.

## Flujo esperado

**Usuario:** «Iris, necesito que investigues algo por mí».

**IRIS, por voz:** «Claro. ¿Sobre qué tema?».

**Usuario:** «Sobre baterías para el robot».

**IRIS, por voz:** confirma que va a consultar y lanza la herramienta.

**IRIS, por voz:** cuenta los hallazgos cuando vuelve la investigación. El usuario
puede seguir conversando durante el trabajo en modo real. La voz principal resume
el resultado del especialista con el contexto de la conversación.

No se requieren botones, formularios ni leer el resultado en una pantalla. El modelo
no debe llamar a una búsqueda sin conocer el tema. Las fuentes se conservan como datos
de la herramienta; la respuesta hablada puede nombrarlas sin dictar URLs largas.

## Dos modos distintos

| | Demo local, sin claves | Sesión real, con APIs |
|---|---|---|
| Entrada | Micrófono → Vosk español | Micrófono → audio PCM → OpenAI Realtime |
| Conversación | Guion limitado y explícito de prueba | Modelo de voz y contexto de sesión |
| Respuesta | Voz española SAPI de Windows | Audio del modelo en streaming |
| Investigación | Simulada; lo anuncia por voz | Gemini o Grok con búsqueda habilitada |
| Interrumpir mientras habla | No: demo por turnos para evitar eco | Implementado: cancela audio pendiente y trunca historial |
| Claves y gasto | No requiere claves ni llama APIs | Requiere claves, acceso a modelos y uso pago |
| Activación | «Iris» al inicio; luego mantiene el diálogo | Se activa al ejecutar `--live`; escucha toda la sesión |

La demo permite comprobar **audio de entrada, reconocimiento, aclaración, llamada al
cerebro y respuesta hablada**. No es todavía una IA local capaz de investigar o conversar
libremente. Su voz es la instalada en Windows, no la voz final del producto.

Vosk se eligió únicamente para una prueba de reconocimiento local liviana sin claves.
Whisper sigue siendo una opción para el pipeline local definitivo. El modelo español
pequeño procede del [catálogo oficial de Vosk](https://alphacephei.com/vosk/models)
y se verifica con SHA-256 antes de extraerlo. La descarga inicial pesa aproximadamente
39 MB; después funciona localmente.

## Ejecución en esta PC

Desde la carpeta del repo:

```powershell
.\.venv\Scripts\python.exe -m iris --demo
```

Decí «Iris, necesito que investigues algo por mí». Esperá que termine de hablar y
contestá el tema. Para dejar la demo en espera: «Iris, dormí». Para terminar el proceso
y liberar el micrófono: **Ctrl+C**. En demo, «cancelar» cancela la tarea cuando está
escuchando. La terminal permite diagnosticar lo reconocido, pero no es parte
obligatoria de la interacción.

En esta PC se detectó **Microsoft Sabina Desktop — Spanish (Mexico)**. Se generó una
muestra WAV con esa voz. No se grabó una conversación del usuario durante la validación.

## Instalación nueva

Requiere Windows, Python 3.11+ y una voz española instalada en Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice]" -c requirements.lock.txt
.\.venv\Scripts\python.exe -m iris --download-model
.\.venv\Scripts\python.exe -m iris --check
.\.venv\Scripts\python.exe -m iris --demo
```

`start.ps1` instala, prepara el modelo si falta y arranca la demo hablada con monitor. No hace
falta cambiar la política de scripts: también podés ejecutar los comandos anteriores
individualmente. `--check` enumera dispositivos/voz; no activa el micrófono.

Si Windows elige otra entrada, usá su índice: `--input-device 1`. La salida de la demo
es la predeterminada de Windows. En modo real se puede elegir `--output-device` de
la lista de PortAudio.

## Activar la conversación real después

Copiar `.env.example` a `.env` y configurar localmente `OPENAI_API_KEY`, más
`GEMINI_API_KEY` o `XAI_API_KEY` según `IRIS_RESEARCH_PROVIDER`. Luego:

```powershell
.\.venv\Scripts\python.exe -m iris --live
```

`--live` activa explícitamente los proveedores reales aunque `.env` diga `demo`.
`--demo` fuerza simulación aunque `.env` diga `live`. Las opciones son excluyentes y
el modo predeterminado es demo.

En modo real, todo el audio capturado durante la sesión se envía a OpenAI; la activación
por palabra clave local aún no está implementada para este modo. Decir «Iris» no es
una barrera de privacidad. **Ctrl+C** o «Iris, dormí» cierra la sesión. El siguiente
inicio necesita volver a ejecutar el programa.

Usar auriculares para la primera validación. El cliente nativo no tiene cancelación
acústica de eco; un parlante abierto puede hacer que Iris se escuche a sí misma. La
integración al robot requiere resolver el eco.

La conexión nativa usa WebSocket y PCM16 mono a 24 kHz. El cliente administra su
reproducción: ante una interrupción vacía el buffer, descarta audio tardío y envía el
punto de truncado al proveedor. El contador aproxima audio enviado al dispositivo,
no el instante acústico exacto del parlante.
[WebSockets Realtime](https://developers.openai.com/api/docs/guides/voice-websockets),
[interrupciones y truncado](https://developers.openai.com/api/docs/guides/realtime-conversations).

## Herramientas y confirmación hablada

`research_web`, `deep_reason` y `device_status` conservan el gestor del núcleo.
`cancel_research` permite al modelo cancelar búsquedas cuando el usuario cambia la
tarea. Los resultados vuelven a la voz sin detener la captura del micrófono.

Para `open_url`, Iris pide por voz una confirmación de la dirección. Sólo una
**transcripción final del nuevo turno del usuario** que diga «confirmo abrir» autoriza
la acción original. Una respuesta diferente la cancela. No se aceptan flags de
aprobación del modelo ni texto de una página. La confirmación vence y no permite
cambiar argumentos. No hay que mirar una pantalla para autorizar.

La navegación sigue limitada a abrir una URL. Controlar clicks, aplicaciones, archivos,
sensores y actuadores es trabajo posterior; no se afirma haberlo implementado aquí.

## Validación y límites

- Pruebas automáticas de diálogo, buffers, cancelación de audio, resultados tardíos,
  trabajos asíncronos y confirmación hablada, además de las pruebas previas del núcleo.
- Integración local con WAV sintético español: «Iris, necesito que investigues algo
  por mí» → transcripción real Vosk → aclaración → segundo audio con tema → respuesta
  sintetizada a WAV. No se utilizó el micrófono del usuario.
- Enumeración real de dispositivos y voz instalada. No se dejó el micrófono abierto.
- Ventana nativa verificada con estados y transcripciones sintéticos, sin abrir
  dispositivos. Pruebas de cierre/cancelación y de observadores desconectados.
- El modo API se verificó con eventos simulados. **Voz cloud, búsqueda real,
  conversación física con micrófono/parlante y latencia real siguen sin validarse**,
  porque no hay claves ni una sesión de audio del usuario.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice,test]" -c requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tests/check_local_speech.py
```

El monitor de escritorio requiere Tkinter, incluido en la instalación habitual de
Python para Windows. Sin `--monitor`, el programa usa voz sin mostrar una ventana.
