"""Ventana temporal de diagnóstico. No importa ni ejecuta herramientas."""
import asyncio
import math
import time

LABELS = {"idle": "En espera", "listening": "Escuchando", "thinking": "Trabajando", "speaking": "Hablando"}
TASKS = {"research_web": "Investigación", "deep_reason": "Análisis", "open_url": "Abrir dirección", "device_status": "Estado del dispositivo"}
STATUS = {"running": "en curso", "awaiting_approval": "esperando confirmación por voz", "completed": "terminada", "cancelled": "cancelada", "failed": "falló", "expired": "vencida"}


class DesktopMonitor:
    def __init__(self, feedback):
        # tkinter is optional and loaded only when the monitor is requested.
        import tkinter as tk
        self.tk, self.feedback = tk, feedback
        self.closed = False
        self.previous = None
        self.root = tk.Tk()
        self.root.title("IRIS · Monitor del prototipo")
        self.root.geometry("760x720")
        self.root.minsize(640, 620)
        self.root.configure(bg="#10161d")
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        header = tk.Frame(self.root, bg="#10161d")
        header.pack(fill="x", padx=28, pady=(24, 12))
        tk.Label(header, text="IRIS", font=("Segoe UI", 22, "bold"), bg="#10161d", fg="#eaf4f5").pack(side="left")
        self.mode = tk.Label(header, font=("Segoe UI", 10), bg="#10161d", fg="#99b7bc")
        self.mode.pack(side="right")
        self.face = tk.Canvas(self.root, height=248, bg="#080e13", highlightthickness=0)
        self.face.pack(fill="x", padx=28)
        self.state = tk.Label(self.root, font=("Segoe UI", 17, "bold"), bg="#10161d", fg="#77dfcf")
        self.state.pack(pady=(12, 4))
        self.capture = tk.Label(self.root, font=("Segoe UI", 10), bg="#10161d", fg="#99b7bc")
        self.capture.pack()
        self.jobs = tk.Label(self.root, font=("Segoe UI", 10), bg="#10161d", fg="#f2c888", justify="left", anchor="w", wraplength=650)
        self.jobs.pack(fill="x", padx=28, pady=(14, 12))
        tk.Label(self.root, text="Registro de prueba", font=("Segoe UI", 10, "bold"), bg="#10161d", fg="#99b7bc", anchor="w").pack(fill="x", padx=28)
        self.messages = tk.Text(self.root, height=7, font=("Segoe UI", 11), bg="#18222d", fg="#eaf4f5", relief="flat", padx=14, pady=10, wrap="word", state="disabled", takefocus=0)
        self.messages.pack(fill="both", expand=True, padx=28, pady=(8, 12))
        self.messages.tag_configure("iris", foreground="#77dfcf")
        self.footer = tk.Label(self.root, font=("Segoe UI", 9), bg="#10161d", fg="#99b7bc", wraplength=650)
        self.footer.pack(padx=28, pady=(0, 16))

    def _request_close(self):
        self.closed = True

    def _eyes(self, expression):
        width, height = self.face.winfo_width(), self.face.winfo_height()
        clock = time.monotonic()
        self.face.delete("eyes")
        color = "#f2c888" if expression == "thinking" else "#77dfcf"
        blink = 0.08 if clock % 5 < 0.12 else 1.0
        eye_width, eye_height = min(width * 0.19, 125), 76 * blink
        if expression == "idle":
            eye_height *= 0.55
            color = "#718f96"
        if expression == "speaking":
            eye_height *= 0.85 + 0.15 * math.sin(clock * 9)
        drift = 8 * math.sin(clock * 2.5) if expression == "thinking" else 0
        for center in (width * 0.34, width * 0.66):
            x, y = center + drift, height / 2
            r = min(20, eye_height / 2)
            left, right, top, bottom = x-eye_width/2, x+eye_width/2, y-eye_height/2, y+eye_height/2
            points = [left+r,top, right-r,top, right,top, right,top+r, right,bottom-r,
                      right,bottom, right-r,bottom, left+r,bottom, left,bottom, left,bottom-r, left,top+r, left,top]
            self.face.create_polygon(points, smooth=True, fill=color, tags="eyes")
            if expression == "listening":
                pulse = 5 + 3 * math.sin(clock * 3)
                self.face.create_oval(left-pulse, top-pulse-12, right+pulse, bottom+pulse+12,
                                      outline="#335954", width=2, tags="eyes")

    def pump(self):
        if self.closed:
            return False
        snapshot = self.feedback.snapshot
        if snapshot != self.previous:
            mode = {"demo": "DEMO LOCAL · SIN CLAVES", "live": "SESIÓN CON APIs", "preview": "VISTA SIMULADA · SIN MICRÓFONO"}.get(snapshot.mode, snapshot.mode)
            self.mode.configure(text=mode)
            footer = "Vista de estados ilustrativos · audio apagado. Cerrar la ventana termina la vista." if snapshot.mode == "preview" else "Hablá con Iris. Esta ventana observa el sistema. Cerrar la ventana termina la sesión."
            self.footer.configure(text=footer)
            self.state.configure(text=LABELS[snapshot.expression])
            capture = "Micrófono activo" if snapshot.capturing else "Micrófono apagado"
            if snapshot.capturing and not snapshot.awake:
                capture += " · esperando «Iris»"
            if snapshot.mode == "demo" and snapshot.speaking:
                capture += " · entrada pausada durante la voz local"
            self.capture.configure(text=capture)
            jobs = snapshot.tasks[-3:]
            self.jobs.configure(text="\n".join(f"{TASKS.get(job.name, job.name)} · {STATUS.get(job.status, job.status)}" for job in jobs) or "Sin tareas en curso")
            if self.previous is None or snapshot.messages != self.previous.messages:
                self.messages.configure(state="normal")
                self.messages.delete("1.0", "end")
                for role, text in snapshot.messages:
                    self.messages.insert("end", f"{role}: {text}\n\n", "iris" if role == "IRIS" else ())
                self.messages.see("end")
                self.messages.configure(state="disabled")
            self.previous = snapshot
        self._eyes(snapshot.expression)
        self.root.update_idletasks()
        self.root.update()
        return not self.closed

    def close(self):
        self.closed = True
        self.root.destroy()


async def with_monitor(run, feedback, view_factory=DesktopMonitor):
    """Tk y asyncio comparten el hilo principal; cerrar cancela y libera el audio."""
    view = view_factory(feedback)
    task = asyncio.create_task(run())
    try:
        while not task.done():
            if not view.pump():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            await asyncio.sleep(0.03)
        await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        view.close()


async def preview(feedback):
    """Escena ilustrativa: ningún dispositivo ni proveedor se inicia."""
    feedback.update(mode="preview", ready=True, awake=True)
    feedback.transcript("Sistema", "Vista simulada. Los estados son ilustrativos; no se está escuchando ni investigando.")
    while True:
        feedback.update(hearing=True)
        feedback.transcript("Vos (ejemplo)", "Iris, investigá baterías para el robot.")
        await asyncio.sleep(2)
        feedback.update(hearing=False, speaking=True)
        feedback.transcript("IRIS", "Dale, lo investigo. [Ejemplo visual, sin audio]")
        await asyncio.sleep(2)
        feedback.update(speaking=False)
        feedback.task("example", "research_web", "running")
        await asyncio.sleep(3)
        feedback.task("example", "research_web", "completed")
        feedback.update(speaking=True)
        feedback.transcript("IRIS", "Acá llegaría el resultado hablado. [Investigación simulada]")
        await asyncio.sleep(3)
        feedback.update(speaking=False)
        await asyncio.sleep(3)
