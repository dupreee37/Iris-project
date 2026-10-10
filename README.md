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

### Asistente de voz nativo — prototipo 0.2

El arranque principal es una aplicación de audio en Windows: **micrófono → conversación
→ herramientas → respuesta por voz**. El núcleo Python administra
trabajos asíncronos, cancelación y adaptadores de OpenAI, Gemini y Grok.

La **demo sin claves** escucha con Vosk local y habla con la voz española de Windows;
usa un diálogo limitado y anuncia que la investigación es simulada. La conversación
real usa OpenAI Realtime por WebSocket y proveedores de investigación, pendiente de
validación con credenciales. El ESP32 todavía no está conectado al backend.

Durante las pruebas, `--monitor` muestra una ventana de escritorio con ojos,
estados, tareas y transcripciones. Observa la conversación; los pedidos y resultados
siguen siendo por voz. `--preview` permite ver una escena simulada sin micrófono.
La ventana se puede retirar al montar el robot: las señales `idle`, `listening`,
`thinking` y `speaking` quedan disponibles para un adaptador de la pantalla física.
El transporte de audio del ESP32 y ese adaptador todavía necesitan implementación.
La ventana de escritorio es temporal y se retirará al mostrar los estados en la pantalla física.

- [Inicio en Windows](docs/INICIO_WINDOWS.md)
- [Voz nativa: uso, arquitectura y límites](docs/VOZ_NATIVA.md)
- [Revisión del firmware y arquitectura del cerebro](docs/CEREBRO.md)

### Hardware publicado

Este repositorio se está construyendo de forma incremental, en paralelo a las pruebas físicas del prototipo. Por ahora está publicado:

- ✅ **Animación de ojos OLED, máquina de estados y micrófono INMP441 por I2S**. El sketch más reciente detecta nivel de sonido por RMS y activa la expresión de escucha. Es una prueba de hardware; todavía no transmite audio ni reconoce palabras.

🔜 Próximamente se irán sumando el resto de los módulos del sistema: pipeline de voz (STT → LLM → TTS), integración de herramientas IoT, percepción visual, y memoria de largo plazo.

---

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
