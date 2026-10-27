# Cerebro con Claude (`--claude`)

IRIS puede pensar con Claude en lugar de depender de OpenAI/Gemini/Grok. Claude no
procesa audio, así que el flujo es:

```text
micrófono PC → Vosk (local) [+ OpenAI gpt-transcribe] → texto → Claude → texto
                                  → ElevenLabs / voz de OpenAI / voz de Windows
                                        │
                  web_search / web_fetch (servidor de Anthropic)
                                        │
                  device_status · open_url · open_app → Brain/ToolManager
```

Claude **decide**, el gestor **ejecuta**: las herramientas locales siguen pasando por
`Brain` y `ToolManager` (validación, tiempos, cancelación). Abrir una URL o una app depende
de `IRIS_CONFIRM_ACTIONS`:

- `natural` (por defecto): si se lo pedís, lo abre directo. Si es IRIS quien lo propone, te
  pregunta y alcanza con «sí», «dale» o «hacelo». Las apps siguen limitadas a la lista
  `IRIS_ALLOWED_APPS`.
- `strict`: la acción queda pendiente hasta que la apruebes en tu turno siguiente con un sí
  casual («sí», «dale», «hacelo», «confirmo»); un «no» o cualquier otra cosa la cancela.
  Pensado para cuando IRIS esté en el robot y haya acciones con más riesgo.

## Puesta en marcha

1. Creá una clave en la consola de Anthropic (console.anthropic.com → API keys) y
   cargá crédito ahí. **El plan de claude.ai / Claude Code no da acceso a la API**: son
   cuentas distintas.
2. `copy .env.example .env` y pegá la clave en `ANTHROPIC_API_KEY=`. `.env` no se sube.
3. Las claves van **sólo en `.env`** (no las pegues en chats ni en commits). Instalá y bajá el modelo de voz local, una sola vez:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe -m iris --download-model
.\.venv\Scripts\python.exe -m iris --claude --monitor
```

Decí «Iris, …» para empezar. «Iris, dormí» cierra la conversación y borra el contexto;
«cancelá» o «para» corta lo que esté pensando.

## Qué puede hacer hoy

- Conversar y razonar (modelo `IRIS_CLAUDE_MODEL`, por defecto `claude-sonnet-5-5`).
- Buscar en internet y leer páginas (`web_search` y `web_fetch` de Anthropic).
- Abrir una URL en el navegador y apps de la lista `IRIS_ALLOWED_APPS`.
- Muletillas («mmm», «a ver…», «sigo en eso…») mientras Claude piensa, precargadas para que
  suenen al instante (`IRIS_FILLERS`), y expresiones naturales en las respuestas.
- Informar estado del equipo anfitrión.
- Publicar `thinking` / `speaking` en `Feedback` para los ojos, igual que la demo.

## Voz y oído (`IRIS_TTS` / `IRIS_STT`, por defecto `auto`)

| Pieza | Opciones | Con `auto` |
|---|---|---|
| Voz | ElevenLabs (`eleven_flash_v2_5`, ~75 ms), voz de OpenAI (`gpt-4o-mini-tts`), voz de Windows | ElevenLabs si hay `ELEVENLABS_API_KEY` y `IRIS_ELEVENLABS_VOICE_ID`; si no, OpenAI si hay clave; si no, Windows |
| Oído | Vosk local, o Vosk + ElevenLabs Scribe v2, o Vosk + `gpt-transcribe` de OpenAI | ElevenLabs si hay `ELEVENLABS_API_KEY`; si no OpenAI si hay clave; si no, Vosk |

- Con el oído de OpenAI, Vosk sólo marca dónde empieza y termina cada frase; únicamente
  esa frase (más medio segundo previo) se envía a retranscribir. Si la nube falla, se usa
  el texto de Vosk.
- Si la voz en la nube falla antes de sonar (clave, cuota, red), IRIS habla con la voz de
  Windows. Si falla a mitad de frase, no la repite.
- Al arrancar, `--claude` imprime qué motores usa. Para forzar todo gratis: `IRIS_TTS=windows`
  e `IRIS_STT=vosk`.
- Para elegir voz de ElevenLabs: `python -m iris --voices` lista ids y nombres.
- `gpt-4o-mini-tts` figura como obsoleto desde enero de 2027 en la documentación de OpenAI;
  sigue funcionando hasta entonces.
- Con voz en la nube el audio sale por la salida predeterminada (o `--output-device`).

## Conversación fluida

- **Habla mientras piensa:** Claude responde en streaming y cada frase suena apenas está
  completa. Medido con las claves reales: saludo simple, primera frase a ~1,9 s; pedido con
  búsqueda web, «Dale, lo busco.» a ~1,6 s y la respuesta a ~8 s (varía según lo que lea).
  ElevenLabs tarda ~0,5 s en empezar a sonar cada frase.
- **Interrupciones (`IRIS_BARGE_IN=true`):** el micrófono sigue abierto mientras IRIS habla.
  Si decís algo que no es el eco de su propia voz (dos palabras nuevas, o «pará», «basta»,
  «esperá», «Iris»), se calla y te escucha. Con parlantes puede confundirse con su eco y
  cortarse sola: usá auriculares o poné `IRIS_BARGE_IN=false`.
- **Correcciones:** si hablás mientras piensa («no, monardez.com»), el pedido anterior y el
  nuevo se mandan juntos; no se pierde el contexto.
- **Nombres propios:** agregá tus nombres y dominios a `IRIS_STT_KEYTERMS` en `.env` para
  que Scribe los escriba bien, y Claude está instruido para buscar la variante más probable
  si un nombre llega deformado.

## Cómo se evita gastar tokens en ruido

Capas, de la más barata a la más cara; cada una corta antes de llegar a Claude:

1. **Vosk como detector de frases:** sólo se retranscribe audio donde hubo voz, nunca silencio. Si hacés una pausa corta, se espera `IRIS_STT_HANGOVER_SECONDS` (0,5 s) antes de cerrar la frase, para no partirla.
2. **Confianza de Scribe:** si la confianza media por palabra es menor a `IRIS_STT_MIN_LOGPROB`,
   la frase se descarta. El valor por defecto es permisivo; afinalo con tu micrófono.
3. **Palabra de activación:** sin decir «Iris» no pasa nada. Pasados `IRIS_AWAKE_SECONDS`
   sin hablar, hay que volver a decirla.
4. **Filtro de una palabra:** estando activa, una palabra suelta (salvo sí, no, gracias,
   dale, listo, cancelá, dormí) se ignora.
5. **Historial compacto:** de cada turno sólo se guarda lo que se dijo; los resultados de
   búsqueda y el razonamiento no se reenvían en los turnos siguientes.
6. **Ajustes de Claude:** esfuerzo `low`, máximo 5 búsquedas y 3 lecturas web por turno,
   respuestas de 1 a 3 oraciones.

`keyterms` (palabras a favorecer, como «Iris») suma 20 % al precio de Scribe; si no lo
querés, `IRIS_STT_KEYTERMS=[]`.

## Costos y límites

- Cada frase reconocida y cada resultado de búsqueda consumen créditos. Sonnet 5.5
  cuesta $2 / $10 por millón de tokens (entrada / salida); `claude-opus-5-5`, $4 / $20,
  y es más capaz. Se cambia con `IRIS_CLAUDE_MODEL`. Las herramientas web usan las variantes
  `_20260209` de Opus 5.5 y Sonnet 5.5.
- Vosk pequeño falla con frases libres y ruido; eso también gasta créditos (el oído en
  la nube de arriba lo mejora). Whisper local sigue como opción gratuita pendiente.
- Pasados 60 mensajes el contexto se reinicia (sin resumen). La memoria de largo plazo
  (RAG) queda pendiente.
- **Todavía no maneja el equipo con mouse/teclado ni navega haciendo clic.** Eso es
  *computer use* de Claude (`computer_toolset_20260801`): requiere capturas de pantalla
  y un ciclo propio, y conviene probarlo en una VM o cuenta aparte. Está pendiente.
- Audio de la placa ESP32 y ojos físicos: igual que en `CEREBRO.md`, aún sin conectar.
- No se probó contra la API real (sin clave en la máquina de desarrollo). Los tests usan
  un cliente simulado y se verificó la forma de la petición HTTP.

## Archivos

- `iris/claude_agent.py`: ciclo de herramientas, confirmaciones e historial.
- `iris/claude_voice.py`: palabra de activación, cancelación y bucle de voz.
- `iris/tools.py`, `iris/brain.py`: `open_app` y `APPROVAL_TOOLS`.
- `iris/speech.py`: voz ElevenLabs/OpenAI, oído en la nube y elección `auto`.
- `tests/test_claude_agent.py`, `tests/test_speech.py`: casos sin red.
