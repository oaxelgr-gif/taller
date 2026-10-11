"""Punto de entrada: sirve la aplicación en toda la red local (0.0.0.0)."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    puerto = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    # host="0.0.0.0" => accesible desde PCs, tablets y celulares de la misma red
    app.run(host="0.0.0.0", port=puerto, debug=debug, threaded=True)
