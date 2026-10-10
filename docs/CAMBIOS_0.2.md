# IRIS 0.2 — cambios para revisar

Esta rama agrega el primer cerebro de voz para probar Iris desde una PC con Windows.
El README describe el objetivo completo del proyecto: un asistente conversacional con
ojos, micrófono, herramientas y un cuerpo físico. Esta entrega se concentra en que el
flujo de voz y las decisiones del cerebro se puedan revisar antes de conectar la placa.

## Lo que se puede probar sin claves

- `python -m iris --demo --monitor` usa el micrófono de la PC, reconoce español en
  local con Vosk, pregunta si falta el tema, y contesta con la voz española instalada
  en Windows. El diálogo es una prueba guiada; la búsqueda se simula y Iris avisa que
  no consultó internet.
- `python -m iris --preview` muestra el monitor y una escena ilustrativa sin abrir
  micrófono, parlante ni servicios de IA.
- «Iris, dormí» deja la demo en espera; `Ctrl+C` o cerrar el monitor liberan el audio.

## Conversación y cerebro

- El modo `--live` conecta entrada y salida PCM mono a 24 kHz con OpenAI Realtime.
  Procesa turnos, interrupciones, cancelación de audio pendiente y devolución de
  resultados al diálogo.
- `Brain` y `ToolManager` administran trabajos asíncronos en paralelo, validan
  argumentos, limitan recursos y admiten cancelación. El modelo solicita herramientas;
  el gestor valida y las ejecuta.
- La investigación tiene adaptadores separados: Gemini con Google Search o xAI con
  web search. El modelo de texto de GPT también tiene su propio adaptador. Las claves
  se configuran localmente en `.env`; el archivo nunca se incluye en la rama.
- Abrir una URL requiere que una transcripción del turno actual del usuario diga
  «confirmo abrir». Otra respuesta cancela la acción.

## Monitor y futuro hardware

- La ventana nativa temporal muestra ojos, estado de audio, tareas y transcripciones.
  La interacción y los resultados se mantienen en la voz.
- No se incluye servidor ni página web; la ventana temporal es el único elemento
  visual de prueba.
- `Feedback` publica estados `idle`, `listening`, `thinking` y `speaking`. Un consumidor
  futuro puede dirigirlos a la pantalla OLED. Los fallos de observación no deben
  detener la conversación.
- `AudioDevice` contiene la captura y reproducción de la PC. Así el transporte del
  prototipo físico podrá integrarse aparte; los paquetes de audio tendrán que adaptar
  los 16 kHz del firmware actual a los 24 kHz de la conversación cloud.
- Los tres sketches originales de Arduino y sus conexiones se conservan. Esta rama
  **todavía no conecta el ESP32 por Serial/MQTT ni transporta audio desde el robot**.

## Archivos de referencia

- `README.md`: objetivo, estado y alcance resumidos.
- `docs/VOZ_NATIVA.md`: instrucciones, arquitectura y límites de la prueba de voz.
- `docs/INICIO_WINDOWS.md`: instalación y comandos.
- `docs/CEREBRO.md`: revisión del firmware existente y decisiones de arquitectura.
- `iris/`: conversación, audio, proveedores, herramientas, monitor y modo de prueba.
- `tests/`: cobertura de diálogo, audio, trabajos, permisos hablados y flujo de eventos.

## Verificación y próximos pasos

La ventana se abrió y sus estados y transcripciones se comprobaron sin activar ningún
dispositivo. El reconocimiento local se probó antes con audio WAV sintético; no se grabó
ni abrió el micrófono del usuario durante esa validación. El código conserva pruebas del
cerebro, voz, proveedores y ventana; esta rama no incluye pruebas de endpoints web.

No se probaron proveedores reales: todavía no había claves configuradas. La conexión
física, cancelación de eco, medición de latencia con APIs y reconocimiento incremental
del modo cloud siguen pendientes. La demo sin claves es por turnos y no reemplaza una
conversación libre con el modelo.
