# IRIS 0.2 — revisión del cerebro y del prototipo

## Objetivo

El README de Iris describe un asistente personal con voz, percepción, memoria,
herramientas y expresiones en pantalla. La regla importante es conservar una capa
explícita entre lo que decide el modelo y lo que el equipo ejecuta.

En esta etapa se desarrolla el cerebro desde la PC con Windows. La conversación y los
resultados se entregan por voz. La ventana de escritorio sólo permite observar ojos,
estado, tareas y transcripciones mientras se arma el prototipo; luego se retira y esos
estados pasan a la pantalla del robot.

## Estado del hardware recibido

La rama base `main` terminaba en `bb1e37a` del 5 de octubre de 2026. El último aporte
del compañero fue el sketch `robot_eyes2_estados_mic.ino`: ESP32-S3, OLED I2C (SDA 8,
SCL 9) e INMP441 por I2S (WS 4, SCK 5, SD 6). Captura a 16 kHz en cuadros de 20 ms y
calcula RMS para expresar actividad de voz. Los nombres de estados también se pueden
ordenar por Serial.

Ese VAD detecta energía de audio; no reconoce palabras ni envía muestras a la PC.
Todavía no existe enlace entre la placa y el cerebro. Se conservaron los tres sketches
Arduino tal como estaban; esta rama agrega el programa Python por separado.

Observaciones para la próxima revisión del sketch: el parpadeo usa `delay()` y puede
pausar el ciclo que consume I2S; el VAD descarta las muestras después de calcular RMS;
el modo autónomo puede cambiar los ojos mientras otro estado está activo. Conviene
medir pérdida de muestras antes de pasar audio y coordinar un solo dueño de la pantalla.
El firmware no se compiló ni se probó en una placa durante esta entrega.

## Flujo que se agregó

```text
Micrófono de la PC → audio de entrada → conversación → solicitudes de herramientas
                                  ↑                         ↓
                             voz de IRIS ← resultados ← gestor de trabajos
                                  ↓
                         Feedback → ventana temporal

Más adelante: transporte de audio de la placa y Feedback → ojos OLED
```

- **Modo demo:** Vosk reconoce frases en español localmente y la voz SAPI de Windows
  responde. Es un guion acotado para probar los turnos de conversación. Sin claves,
  la investigación se simula y se anuncia como simulada.
- **Modo live:** OpenAI Realtime recibe PCM mono de 24 kHz y devuelve voz en streaming.
  El controlador espera el cierre del turno, permite interrupciones y descarta la
  salida vieja si el usuario vuelve a hablar.
- **Gestor:** cada solicitud se valida antes de que corra una herramienta. Los trabajos
  son asíncronos, se pueden cancelar y respetan topes de concurrencia y tiempo.
- **Modelos por tarea:** OpenAI Realtime sostiene la conversación; el gestor enruta la
  búsqueda a Gemini con Google Search o a xAI con web search; GPT por Responses queda
  como especialista en análisis. Los resultados de búsqueda incluyen sus fuentes.
- **Observación:** `Feedback` publica snapshots de `idle`, `listening`, `thinking` y
  `speaking`. Tkinter los muestra en la ventana opcional y no tiene acceso para ejecutar
  tareas. Cerrar la ventana cancela la sesión y libera el audio.

## Uso en Windows

```powershell
.\.venv\Scripts\python.exe -m iris --demo --monitor
.\.venv\Scripts\python.exe -m iris --preview
```

El primer comando activa el micrófono de la PC. Reconoce la frase «Iris, necesito que
investigues algo por mí», pregunta el tema y luego comunica el resultado de la prueba
por voz. Sin claves ni conexión a los proveedores, no busca datos reales. «Iris,
dormí» deja la demo en espera; Ctrl+C o cerrar la ventana libera los dispositivos.

`--preview` sólo representa el flujo en la pantalla: no abre el micrófono, el parlante
ni servicios de IA. La demo hablada es por turnos; no demuestra todavía interrupciones
en el audio local.

Para habilitar `--live`, hay que configurar `OPENAI_API_KEY` y una clave de búsqueda
(`GEMINI_API_KEY` o `XAI_API_KEY`) en `.env`. El modo live envía el audio capturado a
OpenAI desde el inicio de la sesión; no hay palabra de activación local. Usar
auriculares mientras no haya cancelación de eco.

## Límites y siguientes pasos físicos

- No hay página, servidor HTTP ni interfaz de navegador. La única interfaz temporal es
  la ventana visual opcional; el uso del asistente sigue siendo por voz.
- La ventana puede quitarse sin cambiar los proveedores, las herramientas ni el gestor.
  `Feedback.subscribe()` expone los estados para un futuro consumidor de hardware.
- Aún no hay Serial/MQTT entre la PC y el ESP32, transmisión de audio de la placa,
  integración del micrófono I2S, altavoz, cancelación de eco ni control de sensores.
- El firmware actual usa 16 kHz y la sesión cloud 24 kHz. Hay que definir el transporte,
  el remuestreo y la recuperación ante paquetes perdidos antes de probar el cuerpo.
- Vosk sólo sirve para el guion local de esta demo; Whisper es candidato para probar
  reconocimiento local de frases libres. No se midió latencia cloud ni de hardware.
- La sesión live fue verificada con eventos simulados, no con una clave/API real. La
  conexión, los permisos de modelos y el consumo no se validaron en esta entrega.

## Seguridad y manejo de acciones

La demo fuerza simulación incluso si `.env` contiene claves. No consulta APIs ni abre
URLs. En live, el programa valida herramientas y URLs antes de actuar. Abrir una URL
requiere una transcripción completa del turno nuevo del usuario que diga literalmente
«confirmo abrir»; otra respuesta cancela la solicitud. Los resultados de páginas son
datos, no instrucciones para el sistema. El cerebro no afirma tener acceso a archivos,
cámara ni sensores que todavía no estén conectados.

## Recorrido de archivos

- `iris/brain.py`, `iris/tools.py`: ejecución, límites y validación.
- `iris/providers.py`, `iris/config.py`: adaptadores de modelos y claves locales.
- `iris/realtime_voice.py`, `iris/voice.py`: audio cloud, interrupciones y turnos.
- `iris/local_speech.py`, `iris/demo_voice.py`, `iris/dialogue.py`: reconocimiento,
  respuesta local y guion limitado de la prueba sin claves.
- `iris/audio.py`, `iris/feedback.py`, `iris/monitor.py`: audio de la PC y señales de
  estado; visualización opcional.
- `tests/`: verificaciones del cerebro, los proveedores, el flujo de voz y el monitor.
- `docs/CAMBIOS_0.2.md`: resumen para revisar la rama.
