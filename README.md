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

Este repositorio se está construyendo de forma incremental, en paralelo a las pruebas físicas del prototipo. Por ahora está publicado:

- ✅ **Animación base de ojos en pantalla OLED (ESP32 + SSD1306 128x64 I2C)** — el "estado neutral" del rostro expresivo: ojos grandes y azules con parpadeo periódico, que da la primera sensación de "vida" a la interfaz. Es la base sobre la que se construirá la máquina de estados completa (escuchando, procesando, duda/atención, hablando).

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
| Claude API | Razonamiento y selección de herramientas |
| Whisper | Reconocimiento de voz (STT) |
| Piper TTS / ElevenLabs | Síntesis de voz |
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
