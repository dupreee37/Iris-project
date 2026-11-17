# IRIS — Agente Personal Inteligente

> Un agente conversacional con cuerpo físico propio, que ve, escucha y aprende del entorno — más allá del comando de voz.

Proyecto académico de ingeniería (prototipo MVP) que combina hardware embebido, inteligencia artificial y una interfaz emocional expresada a través de una pantalla de ojos animados, en lugar de texto o luces genéricas.

---

## 🧠 ¿Qué es IRIS?

Los asistentes de voz actuales (Alexa, Google Home) entienden **comandos**: el usuario da una orden explícita y el sistema la ejecuta. No razonan sobre contexto, no perciben el entorno y se comunican mediante luces genéricas o pantallas de texto.

**IRIS propone otro paradigma.** Es un agente con:

- 🗣️ **Razonamiento sobre intención**, no solo comandos rígidos
- 👁️ **Percepción del entorno** mediante cámara y sensores (no solo audio)
- 🧩 **Memoria de corto y largo plazo** (RAG) sobre preferencias del usuario
- 😊 **Interfaz emocional**: comunica su estado interno mediante micro-expresiones oculares animadas en una pantalla, sin necesidad de texto
- 🔧 **Arquitectura de herramientas abierta**, en vez de un ecosistema cerrado de fabricante

El principio de diseño central: **el modelo de lenguaje decide, nunca ejecuta directamente**. Toda acción sobre el mundo físico pasa por un gestor de herramientas explícito, lo que hace el sistema auditable y fácil de extender.

---

## 📍 Estado actual del proyecto

### Iris, asistente de voz físico (versión completa)

**Estado: completo.** Iris funciona de punta a punta: una aplicación de voz en Windows se encarga de la conversación, y un robot con cuerpo propio, basado en un ESP32-S3, le pone cara, oído y voz.

La aplicación sigue el flujo **micrófono → conversación → herramientas → respuesta por voz**. El núcleo Python administra trabajos asíncronos, cancelación y adaptadores de OpenAI, Gemini y Grok. El robot refleja lo que sucede con los estados `idle`, `listening`, `thinking` y `speaking`: ojos animados en una pantalla OLED y la voz de Iris saliendo por un parlante propio.

**Modos de ejecución**

| Modo | Qué hace |
|---|---|
| `python -m iris --demo` | Sin claves. Escucha con Vosk local y habla con la voz española de Windows. La investigación es simulada y lo avisa. |
| `python -m iris --claude` | Cerebro con Claude: conversa, busca en la web y abre URLs o apps hablando natural. Usa créditos de la API de Anthropic y ElevenLabs para el oído y la voz. |
| `python -m iris --live` | Conversación real con OpenAI Realtime por WebSocket y proveedores de investigación. Requiere credenciales. |
| `--monitor` / `--preview` | Ventana de escritorio opcional con ojos, estados y transcripciones. `--preview` muestra una escena simulada, sin micrófono. |

`--claude` y `--live` usan APIs de pago y pueden generar cargos.

- [Cerebro con Claude](https://github.com/dupreee37/Iris-project/blob/main/docs/CLAUDE.md)
- [Inicio en Windows](https://github.com/dupreee37/Iris-project/blob/main/docs/INICIO_WINDOWS.md)
- [Voz nativa: uso, arquitectura y límites](https://github.com/dupreee37/Iris-project/blob/main/docs/VOZ_NATIVA.md)
- [Revisión del firmware y arquitectura del cerebro](https://github.com/dupreee37/Iris-project/blob/main/docs/CEREBRO.md)

### Hardware

| Módulo | Función | Conexión (ESP32-S3-N8R2) |
|---|---|---|
| OLED SSD1306 128×64 (I2C) | Ojos y estados | SDA → GPIO8, SCL → GPIO9 |
| Micrófono INMP441 (I2S) | Detecta cuándo le hablan | WS → GPIO4, SCK → GPIO5, SD → GPIO6, L/R → GND |
| Amplificador MAX98357A + parlante (4-8 Ω) | Voz de Iris | BCLK → GPIO15, LRC → GPIO16, DIN → GPIO17, VIN → 5V |

- ✅ Animación de ojos OLED y máquina de estados.
- ✅ Micrófono INMP441 por I2S con detección de voz por nivel RMS, que activa la expresión de escucha.
- ✅ Amplificador MAX98357A y parlante: reproducen la voz de Iris.
- ✅ Conexión con la PC: el backend controla los estados y el audio de la placa por USB.

### Ideas para futuras versiones

Integración de herramientas IoT, percepción visual y memoria de largo plazo.

## 🏗️ Arquitectura (visión general del sistema completo)

```
USUARIO — voz, presencia, gestos
        ▼
INTERFAZ MULTIMODAL — micrófono, cámara, pantalla circular de ojos
        ▼
AGENTE CENTRAL (LLM + razonamiento)
   ├── Memoria (corto / largo plazo)
   ├── Planner (descompone la tarea)
   └── Contexto (sensores + escena)
        ▼
TOOL MANAGER (gestor de herramientas)
   ├── IoT del entorno (luces, relés, sensores)
   ├── Visión (cámara + detección)
   └── Servicios (clima, calendario)
```

## 🛠️ Stack tecnológico (planificado)

| Tecnología | Uso |
|---|---|
| Python | Orquestación del agente, llamadas al LLM, GPIO en Raspberry Pi |
| C++ / Arduino (ESP32) | Firmware de tiempo real para sensores, actuadores y pantalla |
| SQLite / Chroma | Memoria de largo plazo (RAG) |
| MQTT | Comunicación entre Raspberry Pi central y nodos ESP32 |
| OpenAI Realtime / proveedores configurables | Audio nativo por WebSocket; pendiente de prueba con API real |
| Gemini / Grok con búsqueda | Investigación con fuentes, fuera de la ruta inmediata de voz |
| GPT por Responses | Análisis complejo delegado |
| Vosk / Windows SAPI | Reconocimiento y voz local de la demo, sin APIs |
| Whisper / Piper / otros STT y TTS | Candidatos para la variante local definitiva |
| YOLOv8 / MobileNet | Visión por computadora |
| Home Assistant | Middleware de integración IoT |

## 🎯 Alcance del MVP

1. **Núcleo conversacional + control básico** *(en desarrollo)* — pipeline de voz completo, 2-3 herramientas IoT reales, e interfaz de ojos reaccionando a los estados del sistema.
2. **Percepción visual** *(siguiente)* — cámara con detección de objetos liviana.
3. **Memoria de largo plazo** *(siguiente)* — base vectorial simple para preferencias del usuario.
4. Integración avanzada con entorno de trabajo — *fuera de alcance de esta entrega, documentada como línea futura*.

---

## 📚 Contexto académico

Este proyecto atraviesa de forma aplicada más de una docena de áreas de estudio: interacción humano-agente, agentes autónomos, visión por computadora, IoT, memoria artificial/RAG, procesamiento de lenguaje natural, sistemas distribuidos, y robótica básica, entre otras.

> *"IRIS no es un altavoz con luces. Es un ejercicio de ingeniería de agentes: percibir, recordar, razonar y actuar — con un cuerpo físico propio."*

---

*Proyecto en desarrollo activo. Este README se irá actualizando a medida que se publiquen nuevos módulos del sistema.*
