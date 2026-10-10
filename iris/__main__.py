import argparse
import asyncio
from pathlib import Path

from .config import Settings


DEMO_SCRIPT = """Hola, soy Iris. Esta es una demostración de la voz local de Windows.
Si me decís: Iris, necesito que investigues algo por mí, te respondo: Claro, ¿sobre qué tema?
Me indicás el tema y te aviso: Dale, lo investigo.
En modo real, cuando la herramienta termine, te cuento los resultados en voz alta.
Ahora estamos sin claves. Esta grabación es una muestra de interacción, no una investigación real.
"""


def main():
    parser = argparse.ArgumentParser(description="IRIS: asistente de voz nativo para Windows")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Voz local y herramientas simuladas, sin claves (predeterminado)")
    mode.add_argument("--live", action="store_true", help="Conversación real con APIs; transmite audio y puede generar cargos")
    mode.add_argument("--download-model", action="store_true", help="Preparar reconocimiento local español (~39 MB)")
    mode.add_argument("--check", action="store_true", help="Listar dispositivos y voz local, sin activar el micrófono")
    mode.add_argument("--render-demo", type=Path, metavar="WAV", help="Generar muestra hablada a archivo, sin activar dispositivos")
    mode.add_argument("--preview", action="store_true", help="Ver ojos y estados ilustrativos, sin activar audio ni APIs")
    parser.add_argument("--monitor", action="store_true", help="Mostrar ventana temporal de ojos, estados y transcripciones")
    parser.add_argument("--model-path", type=Path, default=Path("work/models/vosk-model-small-es-0.42"))
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int, help="Salida PortAudio para --live; la demo usa la salida predeterminada de Windows")
    args = parser.parse_args()
    if args.monitor and (args.check or args.download_model or args.render_demo):
        parser.error("--monitor acompaña a --demo o --live; --preview ya muestra la ventana")
    try:
        if args.download_model:
            from .local_speech import download_model
            print(download_model())
        elif args.check:
            import pythoncom
            import sounddevice as sd
            from .local_speech import windows_voice
            print(sd.query_devices())
            pythoncom.CoInitialize()
            try:
                print("Voz local:", windows_voice().Voice.GetDescription())
            finally:
                pythoncom.CoUninitialize()
            print("Modelo local:", "listo" if args.model_path.is_dir() else "falta --download-model")
            print("No se abrió el micrófono ni se enviaron datos a APIs.")
        elif args.render_demo:
            from .local_speech import render_wave
            render_wave(DEMO_SCRIPT, args.render_demo)
            print(args.render_demo.resolve())
        else:
            from .feedback import Feedback
            feedback = Feedback(mode="preview" if args.preview else "live" if args.live else "demo")
            async def run():
                if args.preview:
                    from .monitor import preview
                    await preview(feedback)
                elif args.live:
                    from .realtime_voice import run_live
                    await run_live(Settings(), args.input_device, args.output_device, feedback=feedback)
                else:
                    from .demo_voice import run_demo
                    await run_demo(Settings(), args.model_path, args.input_device, feedback=feedback)
            if args.monitor or args.preview:
                from .monitor import with_monitor
                asyncio.run(with_monitor(run, feedback))
            else:
                asyncio.run(run())
    except KeyboardInterrupt:
        print("\nIRIS detenida. Micrófono y salida liberados.")
    except ImportError:
        parser.exit(1, 'Faltan dependencias de voz. Instalá: python -m pip install -e ".[voice]"\n')
    except Exception as exc:
        # No traceback/provider payloads with authorization headers in normal use.
        message = "No se pudo mantener la conexión de voz. Revisá acceso, red y cuota." if args.live else str(exc)
        if args.live:
            try:
                from .local_speech import WindowsSpeaker
                speaker = WindowsSpeaker()
                try:
                    asyncio.run(speaker.say(message))
                finally:
                    speaker.close()
            except Exception:
                pass  # A broken output device must still permit a clean exit.
        parser.exit(1, f"IRIS: {message}\n")


if __name__ == "__main__":
    main()
