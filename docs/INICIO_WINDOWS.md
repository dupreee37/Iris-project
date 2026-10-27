# Iniciar IRIS por voz en Windows

El asistente se usa hablando. La ventana de prueba es opcional y se puede quitar al conectar los ojos físicos.

En esta PC, desde la carpeta del repositorio:

```powershell
.\.venv\Scripts\python.exe -m iris --demo --monitor
```

Decí: **«Iris, necesito que investigues algo por mí»**. Iris responde por voz preguntando
el tema; contestale y esperá la respuesta hablada. La demo reconoce audio real y usa
la voz local de Windows. La investigación es simulada y lo informa por voz.

**Ctrl+C** termina el programa y libera el micrófono. En la demo, «Iris, dormí» vuelve
a espera local. Esperá que termine de hablar antes de responder: la demo local es por
turnos y no pretende demostrar todavía interrupciones en tiempo real.

La ventana temporal muestra ojos, estados, tareas y transcripciones. Cerrarla
también termina la sesión. Ejecutar sin `--monitor` permite usar sólo audio.
Al conectar el robot se podrá sustituir este monitor por la pantalla física.

Para ver únicamente una escena visual simulada, **sin activar el micrófono**:

```powershell
.\.venv\Scripts\python.exe -m iris --preview
```

Instalación nueva:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice]" -c requirements.lock.txt
.\.venv\Scripts\python.exe -m iris --download-model
.\.venv\Scripts\python.exe -m iris --check
.\.venv\Scripts\python.exe -m iris --demo --monitor
```

También se puede ejecutar `./start.ps1` si la política local lo permite; ya inicia
la voz y el monitor de escritorio. Requiere una voz española de Windows y una descarga inicial
de aproximadamente 39 MB para reconocimiento. Después la demo no usa APIs.

Para la conversación con modelos e investigación reales, configurar las claves
localmente en `.env` y ejecutar `python -m iris --live`. Ese modo transmite el audio
de la sesión a OpenAI y requiere acceso/cuota. Usar auriculares al probarlo.

Ver [Voz nativa](VOZ_NATIVA.md) para modos, dispositivos, confirmaciones habladas,
fuentes técnicas y límites de las pruebas realizadas. Si falta Tkinter, instalar el
componente Tcl/Tk del instalador de Python o usar la voz sin `--monitor`.
