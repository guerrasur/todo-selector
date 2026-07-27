"""Arranque en un comando: levanta el server y abre el navegador."""

import threading
import webbrowser

import uvicorn

PUERTO = 8001  # 8000 lo usa Suipacha Loader


def abrir_navegador():
    webbrowser.open(f"http://127.0.0.1:{PUERTO}/")


if __name__ == "__main__":
    threading.Timer(1.5, abrir_navegador).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=PUERTO, reload=False)
