"""Pruebas del director de ritmo y la crónica del mundo (unidad 23b-2, D-179, §B).

Verifica:
B.1: Sin presupuesto o antes de min_gap_days, el director no empieza nada; con ambos,
     empieza un arco que cumple; elección por hash con clave (ponderada por peso).
B.2: Un mundo revuelto (muchos hechos recientes >= calm_events) no recibe un arco nuevo.
B.3: Perfiles: tranquilo empieza menos que caótico en el mismo mundo.
B.4: La crónica guarda una muerte una sola vez (independiente de los deudos), guarda
     ARC_ENDED con su reconocido, y sobrevive intacta a guardar y cargar.
B.5: El narrador recibe entradas relevantes (presencia, lugar, grupo) y nunca una que
     el jugador no pudo saber (hechos no presenciados/no públicos).
B.6: Días vacíos (I-012): un día con solo un hecho observable cuenta como no vacío.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from agora.cognition.narrador import Narrator, Table, _historia
from agora.engine import director
from agora.engine.chronicle import Entrada
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, ArcId, ArcScale, PlaceId
from agora.engine.pack import load_pack
from agora.engine.perception import Percepcion
from agora.engine.state import Bond
from agora.engine.world import Simulation
from agora.health import _Director, _le_contaria_el_narrador

CONFLUENCIA_PACK_PATH = Path("packs/confluencia/pack.yaml")


# =============================================================================
# B.1 — Director de ritmo: presupuesto, intervalo mínimo y clave ponderada
# =============================================================================


def test_b1_director_sin_presupuesto_no_empieza_arco() -> None:
    """B.1: Sin presupuesto suficiente, el director no empieza nada aunque haya calma y plazo."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    tpd = sim.pack.clock.ticks_per_day

    # Pasaron 50 días (supera min_gap_days=20), pero dejamos el presupuesto a 0
    sim.state.tick = 50 * tpd
    sim.state.ultimo_arco = 0
    sim.state.presupuesto = 0.0
    sim.state.hechos_de_ritmo.clear()

    director.pasar_dia(sim)

    assert len(sim.state.arcos) == 0, "El director no debe empezar arcos sin presupuesto"


def test_b1_director_antes_de_min_gap_days_no_empieza_arco() -> None:
    """B.1: Antes de min_gap_days desde el último arco, el director no empieza nada."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    tpd = sim.pack.clock.ticks_per_day

    # Presupuesto abundante (10.0), pero el último arco fue hace 10 días (min_gap_days es 20)
    sim.state.tick = 20 * tpd
    sim.state.ultimo_arco = 10 * tpd
    sim.state.presupuesto = 10.0
    sim.state.hechos_de_ritmo.clear()

    director.pasar_dia(sim)

    assert len(sim.state.arcos) == 0, "El director no debe empezar arcos antes de min_gap_days"


def test_b1_director_con_presupuesto_y_tras_gap_empieza_arco_y_descuenta_coste() -> None:
    """B.1: Con presupuesto y tras min_gap_days, empieza un arco que cumple y gasta su coste."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    tpd = sim.pack.clock.ticks_per_day

    sim.state.tick = 35 * tpd
    sim.state.ultimo_arco = 0
    presupuesto_inicial = 5.0
    sim.state.presupuesto = presupuesto_inicial
    sim.state.hechos_de_ritmo.clear()

    director.pasar_dia(sim)

    assert len(sim.state.arcos) == 1, "Debe empezar exactamente un arco"
    arco_iniciado = next(iter(sim.state.arcos.values()))
    assert arco_iniciado.arco in (ArcId("incursion"), ArcId("epidemia"))

    # Verifica que el coste de la escala fue descontado
    perfil = pack.director.profiles[pack.director.profile]  # type: ignore[union-attr]
    coste_esperado = perfil.cost[ArcScale.CRISIS]
    presupuesto_esperado = presupuesto_inicial + perfil.budget_per_day - coste_esperado
    assert abs(sim.state.presupuesto - presupuesto_esperado) < 1e-6


def test_b1_director_eleccion_por_hash_con_clave_ponderada_no_por_id() -> None:
    """B.1 / M1: La elección se hace por clave hash ponderada por peso (u ** (1/peso)), no por id.

    En confluencia los candidatos son 'epidemia' (peso 0.6) e 'incursion' (peso 1.0).
    Por orden de id simple, 'incursion' > 'epidemia' ganaría siempre al desempatar por max id.
    Comprueba:
    1) Caso donde clave(epidemia) > clave(incursion): gana epidemia (M1 director por id falla).
    2) Caso donde u(epidemia) > u(incursion) pero por peso=0.6 clave(incursion) > clave(epidemia):
       gana incursion, verificando que la ponderación por peso se aplica activamente.
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    perfil = pack.director.profiles[pack.director.profile]  # type: ignore[union-attr]

    # Caso 1: Seed 3, Día 1
    # u_inc = 0.040 -> c_inc = 0.040
    # u_epi = 0.657 -> c_epi = 0.657 ** (1/0.6) = 0.497
    # 0.497 > 0.040: gana epidemia. (Si fuera por id 'incursion' > 'epidemia', ganaría incursion).
    sim1 = Simulation(pack, seed=3)
    sim1.state.presupuesto = 10.0
    elegido1 = director._elegir(sim1, perfil, dia=1)
    assert elegido1 is not None
    assert elegido1[0].id == ArcId("epidemia"), "Debe ganar epidemia por mayor clave ponderada"

    # Caso 2: Seed 1, Día 5
    # u_inc = 0.880 -> c_inc = 0.880
    # u_epi = 0.901 -> c_epi = 0.901 ** (1/0.6) = 0.840
    # Aunque u_epi > u_inc, por la ponderación c_inc > c_epi, por lo que gana incursion.
    sim2 = Simulation(pack, seed=1)
    sim2.state.presupuesto = 10.0
    elegido2 = director._elegir(sim2, perfil, dia=5)
    assert elegido2 is not None
    assert elegido2[0].id == ArcId("incursion"), "Debe ganar incursion por efecto de la ponderación"


# =============================================================================
# B.2 — Ritmo de hechos y mundo revuelto
# =============================================================================


def test_b2_mundo_revuelto_no_recibe_arco_nuevo() -> None:
    """B.2 / M2: Un mundo revuelto (ritmo_reciente > calm_events) no recibe un arco nuevo.

    Comprueba que al calmarse el ritmo sí lo recibe.
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    tpd = sim.pack.clock.ticks_per_day
    sim.state.tick = 30 * tpd
    sim.state.ultimo_arco = 0
    sim.state.presupuesto = 10.0

    # calm_events para equilibrado es 1.5. Inyectamos 14 hechos en los últimos 7 días:
    # 14 / 7 = 2.0 hechos/día > 1.5
    sim.state.hechos_de_ritmo = {25: 7, 26: 7}
    assert director.ritmo_reciente(sim) == 2.0

    director.pasar_dia(sim)
    assert len(sim.state.arcos) == 0, "Un mundo revuelto no debe recibir arco nuevo"

    # Ahora el mundo se calma: ritmo reciente = 0.0 <= 1.5
    sim.state.hechos_de_ritmo.clear()
    assert director.ritmo_reciente(sim) == 0.0

    director.pasar_dia(sim)
    assert len(sim.state.arcos) == 1, "Un mundo en calma sí debe recibir un arco nuevo"


# =============================================================================
# B.3 — Perfiles de ritmo
# =============================================================================


def test_b3_perfil_tranquilo_empieza_menos_arcos_que_caotico_en_mismo_mundo() -> None:
    """B.3: En el mismo mundo y semilla, el perfil tranquilo empieza menos arcos que el caótico."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)

    def simular_arcos_iniciados(perfil_nombre: str, dias: int = 120) -> int:
        p = pack.model_copy(
            update={"director": pack.director.model_copy(update={"profile": perfil_nombre})}  # type: ignore[union-attr]
        )
        sim = Simulation(p, seed=42)
        tpd = sim.pack.clock.ticks_per_day
        iniciados = 0
        for dia in range(dias):
            sim.state.tick = dia * tpd
            antes = set(sim.state.arcos)
            director.pasar_dia(sim)
            nuevos = set(sim.state.arcos) - antes
            if nuevos:
                iniciados += len(nuevos)
                # Liberar arcos para permitir que el ciclo continúe
                sim.state.arcos.clear()
        return iniciados

    arcos_tranquilo = simular_arcos_iniciados("tranquilo")
    arcos_caotico = simular_arcos_iniciados("caotico")

    assert arcos_tranquilo < arcos_caotico, (
        f"Tranquilo ({arcos_tranquilo}) debe empezar menos arcos que caótico ({arcos_caotico})"
    )


# =============================================================================
# B.4 — Crónica del mundo: muertes, arcos terminados y persistencia
# =============================================================================


def test_b4_cronica_guarda_muerte_una_sola_vez_independiente_de_deudos() -> None:
    """B.4 / M3: La crónica guarda una muerte una sola vez aunque haya múltiples dolientes."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    victima = sim.state.agents_in_order()[0].spec_id

    # Aseguramos que la víctima tenga al menos 5 dolientes con aprecio positivo
    dolientes = [a.spec_id for a in sim.state.agents_in_order()[1:6]]
    for d in dolientes:
        sim.state.agents[d].bonds[victima] = Bond(regard=0.8)

    sim.morir(victima, porque="pelea")

    muertes_en_cronica = [e for e in sim.state.cronica.about(victima) if e.tipo == "muerte"]
    assert len(muertes_en_cronica) == 1, (
        f"Se esperaba 1 muerte en crónica, hay {len(muertes_en_cronica)}"
    )
    assert muertes_en_cronica[0].quienes == (victima,)
    assert muertes_en_cronica[0].texto_clave == "pelea"


def test_b4_cronica_guarda_arc_ended_con_su_reconocido() -> None:
    """B.4: La crónica guarda el desenlace ARC_ENDED con su reconocido y rama."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    reconocido = AgentId("heroe_del_valle")
    lugar = PlaceId("plaza_enana")

    sim._registrar(
        tick=15,
        kind=EventKind.ARC_ENDED,
        place=lugar,
        data={"arco": "incursion", "rama": "resiste", "reconocido": str(reconocido)},
    )

    entradas = sim.state.cronica.about(reconocido)
    assert len(entradas) == 1, "Debe registrarse el ARC_ENDED en la crónica"
    e = entradas[0]
    assert e.tipo == "arco"
    assert e.quienes == (reconocido,)
    assert e.lugar == lugar
    assert e.texto_clave == "resiste"


def test_b4_cronica_sobrevive_intacta_guardar_y_cargar(tmp_path: Path) -> None:
    """B.4 / M5: La crónica se guarda y recupera intacta tras guardar y cargar."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)

    heroe = AgentId("heroe_reconocido")
    sim._registrar(
        tick=10,
        kind=EventKind.ARC_ENDED,
        place=PlaceId("plaza_enana"),
        data={"arco": "incursion", "rama": "resiste", "reconocido": str(heroe)},
    )

    archivo = tmp_path / "partida_cronica.json"
    sim.save(archivo)

    resumed = Simulation.resume(archivo, pack)
    assert len(resumed.state.cronica) == len(sim.state.cronica)
    assert len(resumed.state.cronica) > 0
    assert resumed.state.cronica.entradas == sim.state.cronica.entradas
    assert resumed.state.cronica.about(heroe) == sim.state.cronica.about(heroe)


# =============================================================================
# B.5 — Narrador: relevancia y confidencialidad de la crónica
# =============================================================================


def test_b5_narrador_recibe_entradas_relevantes_y_nunca_privadas() -> None:
    """B.5 / M4: El narrador recibe entradas relevantes y nunca una que el jugador no pudo saber.

    - Hechos públicos (muerte) o presenciados son conocidos.
    - Hechos privados (pareja ajena no presenciada y sin rumor) nunca llegan al narrador (M4).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    yo = sim.state.agents_in_order()[0].spec_id
    presente = sim.state.agents_in_order()[1].spec_id
    lugar_jugador = sim.state.agents[yo].at
    secreto_1 = AgentId("agente_secreto_1")
    secreto_2 = AgentId("agente_secreto_2")

    # Entrada 1: Privada (pareja ajena en linde_salvaje, el jugador no es testigo ni lo oyó)
    sim.state.cronica.anotar(
        Entrada(
            tick=1,
            tipo="pareja",
            quienes=(secreto_1, secreto_2),
            lugar=PlaceId("linde_salvaje"),
            grupo=None,
            texto_clave="pareja",
            testigos=(),
        )
    )

    # Entrada 2: Relevante (el jugador estuvo presente y fue testigo con alguien presente)
    sim.state.cronica.anotar(
        Entrada(
            tick=2,
            tipo="pareja",
            quienes=(presente, AgentId("companero")),
            lugar=lugar_jugador,
            grupo=None,
            texto_clave="pareja",
            testigos=(yo,),
        )
    )

    # Entrada 3: Pública relevante (muerte en el lugar del jugador)
    victima_publica = AgentId("victima_notable")
    sim.state.cronica.anotar(
        Entrada(
            tick=3,
            tipo="muerte",
            quienes=(victima_publica,),
            lugar=lugar_jugador,
            grupo=None,
            texto_clave="caída",
            testigos=(),
        )
    )

    historia = _historia(sim.state, str(yo))
    textos_historia = [h[1] for h in historia]
    todos_los_nombres = {n for h in historia for n in h[2]}

    # La privada NUNCA entra
    assert not any("agente_secreto" in t for t in textos_historia), (
        "Una entrada privada que el jugador no pudo presenciar ni oír no debe llegar a la historia"
    )
    assert "agente_secreto_1" not in todos_los_nombres
    assert "agente_secreto_2" not in todos_los_nombres

    # Las relevantes y públicas SÍ entran
    assert any("se hicieron pareja" in t for t in textos_historia)
    assert any("murió" in t for t in textos_historia)

    # Comprueba también a través de Narrator.world
    narrador = Narrator(providers=(), table=Table())
    told = narrador.world(sim.state, (), str(yo))
    # En fallback, las frases de historia se incorporan a la narración
    assert "agente_secreto" not in told.text


# =============================================================================
# B.6 — Días vacíos (I-012): propio y observable
# =============================================================================


def test_b6_dias_vacios_un_dia_con_solo_un_hecho_observable_cuenta_como_no_vacio() -> None:
    """B.6 / M6: Un día con solo un hecho observable cuenta como no vacío (cubre I-012 y M6).

    Si un agente no tiene paso de trama propio pero presenció un combate observable,
    el día no debe contarse como vacío.
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    agente = sim.state.agents_in_order()[0]
    quien = agente.spec_id
    sim.state.agents = {quien: agente}

    # Caso A: Sin trama propia ni hechos observables -> cuenta como día vacío
    tally_vacio = _Director()
    tally_vacio.cierra_dia(sim)
    assert tally_vacio.personas_dia == 1
    assert tally_vacio.vacios == 1, "Un día sin nada debe contar como vacío"

    # Caso B: Sin trama propia pero con un hecho observable (presenció un combate)
    tally_observable = _Director()
    sim.state.percepcion[quien] = deque([
        Percepcion(
            seq=1,
            tick=0,
            kind=EventKind.COMBAT,
            actor=None,
            target=None,
            place=agente.at,
            action=None,
        ),
    ])
    assert _le_contaria_el_narrador(sim.state, quien) is True

    tally_observable.cierra_dia(sim)
    assert tally_observable.personas_dia == 1
    assert tally_observable.vacios == 0, (
        "Un día con solo un hecho observable NO debe contar como vacío (M6 cuenta solo lo propio)"
    )
