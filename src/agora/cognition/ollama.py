"""`CognitionProvider` contra un Ollama local, con la biblioteca estándar.

Todo fallo es `None`: red caída, tiempo agotado, JSON roto o fuera de esquema.
El puerto lo exige, y es lo que deja correr la partida igual con el modelo
apagado.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from pydantic import BaseModel, ValidationError


class OllamaProvider:
    def __init__(
        self,
        url: str = "http://localhost:11434",
        modelo: str = "llama3.2:latest",
        timeout: float = 60.0,
        temperatura: float = 0.7,
        contexto: int = 8192,
    ) -> None:
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.temperatura = temperatura
        self.contexto = contexto
        """Sin fijarlo, Ollama corta en 4096 tokens por su cuenta y se queda con
        el final del prompt: en el banco de la 14, un 7B sin las instrucciones
        contestó «salir» a «remato al herido»."""

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        # Prosa sola (20a): sin `format`, el modelo contesta texto libre.
        formato: object | None = (
            schema.model_json_schema() if isinstance(schema, type) and issubclass(schema, BaseModel)
            else None if schema is str else "json"
        )
        cuerpo = json.dumps({
            "model": self.modelo, "prompt": briefing, "stream": False,
            **({"format": formato} if formato is not None else {}),
            "options": {"temperature": self.temperatura, "seed": semilla, "num_predict": 160,
                        "num_ctx": self.contexto},
        }).encode()
        peticion = urllib.request.Request(
            f"{self.url}/api/generate", data=cuerpo, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as r:
                respuesta = json.loads(r.read())["response"]
            if schema is str:
                return (respuesta or "").strip() or None
            datos: object = json.loads(respuesta)
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                return schema.model_validate(datos)
            return datos
        except (urllib.error.URLError, TimeoutError, OSError, KeyError,
                json.JSONDecodeError, ValidationError):
            return None
