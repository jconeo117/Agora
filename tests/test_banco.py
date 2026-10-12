"""Pruebas de datos, ejemplos y el banco de intenciones (unidad 14, §B.5)."""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.banco import load_bank, run_bank
from agora.cognition.ollama import OllamaProvider
from agora.engine.ontology import ActionId
from agora.engine.pack import load_pack
from agora.rules.system import load_ruleset

ISLA_PACK = Path("packs/isla/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
BANCO_PATH = Path("packs/isla/banco-intenciones.jsonl")


@pytest.fixture(autouse=True)
def _local_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_load_pack_isla_examples_no_vacio() -> None:
    # 1. load_pack de isla: action_by_id["atacar"].examples no vacío.
    pack = load_pack(ISLA_PACK)
    atacar = pack.action_by_id[ActionId("atacar")]
    assert len(atacar.examples) > 0


def test_load_ruleset_examples_desconocidos_falla(tmp_path: Path) -> None:
    # 2. load_ruleset con combat.examples: {volar: [..]} falla nombrando volar.
    raw = yaml.safe_load(BASE_RULES.read_text(encoding="utf-8"))
    raw["combat"]["examples"] = {"volar": ["vuelo por los aires"]}
    tmp = tmp_path / "bad_rules.yaml"
    tmp.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="volar"):
        load_ruleset(tmp)


def test_ollama_provider_envia_num_ctx_8192() -> None:
    # 3. OllamaProvider.think envía options.num_ctx == 8192 (servidor local).
    cuerpo_recibido: dict[str, Any] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal cuerpo_recibido
            length = int(self.headers.get("Content-Length", 0))
            cuerpo_recibido = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"response": json.dumps({"ok": True})}).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        provider = OllamaProvider(url=f"http://127.0.0.1:{port}", modelo="test-model")
        provider.think("hola", dict, 123)
        assert "options" in cuerpo_recibido
        assert cuerpo_recibido["options"].get("num_ctx") == 8192
    finally:
        server.shutdown()


def test_contrato_del_banco_con_lexico() -> None:
    # 4. run_bank(isla, base, load_bank(banco), None): aciertos == 50,
    # rescatables == 12, falsos_si == 5, crudas_bien == 3, sin_modelo == 0.
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    casos = load_bank(BANCO_PATH)
    informe = run_bank(pack, ruleset, casos, None)

    assert informe.aciertos == 50
    assert informe.rescatables == 12
    assert informe.falsos_si == 5
    assert informe.crudas_bien == 3
    assert informe.sin_modelo == 0
