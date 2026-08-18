"""Memoria episódica: qué recuerda cada quién, y con cuánta fuerza.

El log ya guarda todo lo que pasó, indexado por actor y por lugar. Eso **no es
memoria**: es el registro omnisciente del mundo. La diferencia entre las dos es
el olvido y la importancia — nadie recuerda cinco años de comidas, y de las que
recuerda no recuerda todas igual.

Tres decisiones gobiernan el módulo, y las tres se tomaron contra una alternativa
que parecía más simple.

**El recuerdo es autónomo, no un puntero al log.** La firma original del puerto
era `remember(owner, event_id, ...)` y `recall` devolvía ids. No funciona, y no
por elegancia: el log tiene ventana, así que `log[seq]` de un recuerdo viejo
levanta `EventoDesalojadoError`; y `persistence.py` no guarda la historia, así
que al reanudar una partida **todos los punteros apuntarían a nada**. Un recuerdo
lleva su propia copia de lo saliente. El `seq` se conserva como enlace de vuelta
—sirve al narrador de F5 mientras el evento siga retenido— pero recuperar no lo
desreferencia nunca.

**La señal de recuperación es estructural, no textual.** `recall(owner, cue: str)`
invitaba a dos cosas malas: vocabulario de ambientación dentro del motor —que
`test_agnosticism.py` prohíbe y verifica por AST— y similitud vectorial, que
rompe el determinismo y la legibilidad, que son las dos garantías del proyecto.
Un `Cue` es un puñado de ids del propio motor y la relevancia es coincidencia
contada. Se puede explicar por qué salió un recuerdo y no otro.

**Se olvida por valor, no por antigüedad.** Descartar el más viejo es la política
obvia y es exactamente la que garantiza olvidar lo que importa: el día que te
rompieron el brazo queda enterrado por doscientas cenas. Aquí se descarta el de
menor valor retenido —importancia por desdibujado—, así que un recuerdo intenso
sobrevive a mucha rutina reciente.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from agora.engine.events import Event, EventKind
from agora.engine.ontology import ActionId, AgentId, PlaceId, SituationId
from agora.engine.outcome import signed_saturation


@dataclass(frozen=True, slots=True)
class Cue:
    """Por qué se pregunta. Todos los campos opcionales; ninguno es texto libre.

    Es el sustituto del `cue: str` que declaraba el puerto. Cada campo tiene hoy
    un consumidor previsto y ninguno se añadió "por si acaso":

    - `place` → el miedo a un sitio (*la plaza donde ahorcaron a mi hermano*)
    - `action` → el arrepentimiento (*la última vez que bajé a la sima*)
    - `about` → el miedo o el afecto a una persona concreta

    Un `Cue` vacío no es un error: significa "lo más saliente que tengas", que es
    lo que querrá el narrador de F5 para abrir una escena.
    """

    place: PlaceId | None = None
    action: ActionId | None = None
    about: AgentId | None = None

    def relevance(self, memory: Recuerdo) -> int:
        """Cuántos campos del cue casan con el recuerdo. 0 = no viene a cuento.

        Contar coincidencias y no puntuarlas es deliberado: con tres campos, una
        ponderación sería tres perillas más que calibrar para distinguir casos
        que en la práctica no se dan juntos. Si algún día se dan, se pondera.
        """
        aciertos = 0
        if self.place is not None and self.place == memory.place:
            aciertos += 1
        if self.action is not None and self.action == memory.action:
            aciertos += 1
        if self.about is not None and self.about == memory.about:
            aciertos += 1
        return aciertos

    @property
    def vacio(self) -> bool:
        return self.place is None and self.action is None and self.about is None


@dataclass(frozen=True, slots=True)
class Recuerdo:
    """Un hecho que a alguien se le quedó grabado.

    Inmutable como el `Event` del que sale, y por la misma razón: el pasado no se
    reescribe. Lo que cambia con el tiempo es lo que *vale*, y eso se calcula al
    leer (ver `valor`), no se actualiza en un bucle por tick.

    Los campos son un subconjunto de los de `Event`, no una referencia a él. Ver
    la nota del módulo sobre por qué.
    """

    seq: int
    """El `seq` del evento original. Enlace de vuelta, nunca se desreferencia
    para recuperar: el evento puede haber salido de la ventana o de la partida."""

    tick: int
    kind: EventKind
    place: PlaceId | None = None
    action: ActionId | None = None
    about: AgentId | None = None
    """El otro implicado. Es el `subject` del evento, renombrado porque desde
    dentro del recuerdo no es el sujeto de nada: es de quién va."""

    importancia: float = 0.0
    """Cuánto marcó, en [0, 1). Se fija al recordar y no cambia — lo que cambia
    es cuánto queda de ella."""

    culpable: SituationId | None = None
    """Qué le estaba pasando al mundo, si eso fue la causa. **Es lo que separa un
    recuerdo de un miedo.**

    Sin este campo, el miedo a lugares es imposible de construir bien, y eso se
    descubrió midiendo. Un `NEED_CRITICAL` se dispara donde el agente esté de pie
    cuando una necesidad cruza el umbral, que casi siempre es su cama o su
    taller: temer el sitio donde te entró hambre es un sinsentido, y peor, el
    hambre entra donde uno pasa más tiempo, así que el mecanismo produciría miedo
    a la propia casa. Sistemáticamente y para todos.

    Con el marcador, el lugar deja de ser *dónde estabas* y pasa a ser *parte de
    por qué*. Solo lo ponen las crisis que una situación causó — el cuarto canal
    aplicando daño a quien está dentro de su alcance.

    `None` es lo normal: la mayoría de lo que se recuerda no lo provocó el mundo.
    """

    valencia: float = 0.0
    """Si salió mejor o peor de lo esperado, en [-1, 1]. **Es lo que separa un
    recuerdo de un arrepentimiento.**

    Va aparte de la importancia y no multiplicada dentro de ella porque son dos
    preguntas distintas: *cuánto marcó* y *hacia qué lado*. Una alegría enorme y
    un desastre enorme se recuerdan igual de bien —la importancia toma la
    sorpresa en valor absoluto— y solo aquí se distinguen.

    0.0 es lo normal: un recuerdo sin signo es algo que pasó, ni bueno ni malo.
    """

    def valor(self, tick: int, fade: float) -> float:
        """Lo que este recuerdo pesa HOY: importancia desdibujada por el tiempo.

            valor = importancia * fade ** (ticks transcurridos)

        Misma forma que `Bond.regard_at`, y a propósito la misma: dos mecanismos
        que dicen medir el paso del tiempo tienen que hacerlo igual, o divergen
        en silencio y nadie se entera hasta que hay que explicar una conducta.
        """
        if fade >= 1.0:
            return self.importancia
        return self.importancia * fade ** max(0, tick - self.tick)


def importancia_de(
    urgencia: float,
    sorpresa: float,
    testigos: int,
    *,
    peso_urgencia: float,
    peso_sorpresa: float,
    peso_testigos: float,
    escala: float,
) -> float:
    """Cuánto marca lo que acaba de pasar. Devuelve [0, 1).

        bruto        = w_u * urgencia + w_s * |sorpresa| + w_t * saturación(testigos)
        importancia  = bruto / (bruto + escala)

    Los tres términos son los que `PLAN.md` dejó escritos, y cada uno responde a
    una pregunta distinta sobre el mismo momento:

    **Urgencia** — cuánto te apretaba. Comer con hambre se recuerda; picar algo
    por costumbre, no. Es la misma `urgency` con la que se decidió y con la que
    se valoró el rato, así que la vara es una sola en todo el motor.

    **Sorpresa** — cuánto se desvió de lo esperado, en valor absoluto. Sale
    gratis: `learn` ya calcula ese error para corregir las creencias, y hasta
    ahora lo tiraba. Va en absoluto porque marca lo mismo que algo salga mucho
    mejor de lo previsto que mucho peor; el **signo** es cosa del arrepentimiento
    y se guarda aparte, no aquí.

    **Testigos** — si había alguien delante. Saturado, porque la diferencia entre
    solo y acompañado es enorme y la que va de cuatro a cinco personas no existe.

    La normalización final es la misma curva de `signed_saturation` que usan la
    compañía y el aprecio. No es reutilización por ahorrar líneas: si cada
    mecanismo trajera su propia forma de acotar, `escala` significaría cosas
    distintas en sitios distintos del mismo pack.
    """
    bruto = (
        peso_urgencia * max(0.0, urgencia)
        + peso_sorpresa * abs(sorpresa)
        + peso_testigos * signed_saturation(float(max(0, testigos)))
    )
    if bruto <= 0.0 or escala <= 0.0:
        return 0.0
    return signed_saturation(bruto, escala)


@dataclass(slots=True)
class MemoriaEpisodica:
    """Lo que recuerda cada agente. Una clase y no un dict suelto a propósito.

    El puerto `MemoryStore` prometía que cambiar a sqlite-vec o a Qdrant fuera
    sustituir una clase; eso solo se cumple si hay una clase. Aquí vive además la
    política de olvido, que es lo que no se puede repartir entre los sitios que
    escriben recuerdos.

    **`owner` es obligatorio en todas las operaciones**, y sigue siéndolo por la
    razón con la que se declaró el puerto: hace imposible consultar memoria sin
    decir de quién es, y con ello imposible el bug de omnisciencia — un NPC
    recordando lo que solo presenció otro. En AIDA esa misma firma pasa a ser
    aislamiento entre usuarios, que es requisito legal y no elegancia.
    """

    capacidad: int = 0
    """Cuántos recuerdos retiene cada agente. 0 desactiva el mecanismo entero.

    Apagado por defecto, como `bond_rate` y `sighting_horizon`: un pack que no lo
    pide no paga por él, y añadir el módulo no puede mover ningún contrato ya
    medido.
    """

    fade: float = 1.0
    """Desdibujado por tick. 1.0 = nada se desvanece."""

    _por_duenyo: dict[AgentId, list[Recuerdo]] = field(default_factory=dict)

    def __len__(self) -> int:
        return sum(len(v) for v in self._por_duenyo.values())

    def de(self, owner: AgentId) -> tuple[Recuerdo, ...]:
        """Todo lo que este agente recuerda, en orden de ocurrencia.

        Para inspección y para los tests. Recuperar de verdad es `recall`.
        """
        return tuple(self._por_duenyo.get(owner, ()))

    def duenyos(self) -> Iterator[AgentId]:
        """Quiénes tienen algo guardado. Ordenado: se serializa desde aquí y dos
        guardados del mismo mundo tienen que salir byte a byte iguales."""
        return iter(sorted(self._por_duenyo))

    def remember(
        self,
        owner: AgentId,
        event: Event,
        importancia: float,
        valencia: float = 0.0,
        culpable: SituationId | None = None,
    ) -> Recuerdo | None:
        """Graba un hecho. Devuelve el recuerdo, o `None` si no se guardó.

        Recibe el **evento**, no su id, por lo que explica la nota del módulo: el
        recuerdo tiene que sobrevivir a la ventana del log y a un `save`/`load`.

        Se descarta en el sitio lo que no marcó nada. Sin este filtro, la
        capacidad se llena de rutina y el olvido por valor tiene que hacer el
        trabajo que debió hacer el umbral — con el mismo resultado y habiendo
        pagado por almacenarlo.
        """
        if self.capacidad <= 0 or importancia <= 0.0:
            return None

        recuerdo = Recuerdo(
            seq=event.seq,
            tick=event.tick,
            kind=event.kind,
            place=event.place,
            action=event.action,
            about=event.subject if event.subject != owner else event.actor,
            importancia=importancia,
            valencia=max(-1.0, min(1.0, valencia)),
            culpable=culpable,
        )
        guardados = self._por_duenyo.setdefault(owner, [])
        guardados.append(recuerdo)
        if len(guardados) > self.capacidad:
            self._olvidar(guardados, event.tick)
        return recuerdo

    def _olvidar(self, guardados: list[Recuerdo], tick: int) -> None:
        """Descarta el de menor valor retenido. **No el más viejo.**

        Es la línea que responde al riesgo que `PLAN.md` dejó anotado: *el
        criterio no puede ser solo recencia o se olvidará justo lo importante*.
        Con FIFO, cualquier cosa memorable queda enterrada por la rutina de los
        días siguientes, que es justo al revés de como funciona una biografía.

        Desempate por `seq` para que el orden no dependa de la comparación de
        floats cuando dos valores coinciden — el mismo cuidado que `_rank` en la
        deliberación, y por el mismo motivo: sin él, dos procesos con la misma
        semilla podrían divergir.
        """
        peor = min(range(len(guardados)), key=lambda i: (guardados[i].valor(tick, self.fade),
                                                         guardados[i].seq))
        del guardados[peor]

    def recall(self, owner: AgentId, cue: Cue, limit: int) -> tuple[Recuerdo, ...]:
        """Lo que a este agente le viene a la cabeza, de más a menos presente.

            orden = relevancia · valor(hoy)

        Los dos factores multiplican y no suman, y esa es toda la diferencia
        entre una memoria y un archivo: **un recuerdo que no viene a cuento no
        sale por muy grabado que esté.** Con suma, el trauma más intenso de la
        biografía contamina cualquier pregunta.

        Con un cue vacío se devuelve lo más saliente sin filtrar, que es lo que
        querrá el narrador de F5 para abrir una escena.

        Devuelve `Recuerdo`, no ids de evento. La firma del puerto prometía ids;
        ver la nota del módulo sobre por qué no podía cumplirse.
        """
        if limit <= 0:
            return ()
        guardados = self._por_duenyo.get(owner)
        if not guardados:
            return ()

        vacio = cue.vacio
        puntuados: list[tuple[float, int, Recuerdo]] = []
        for recuerdo in guardados:
            relevancia = 1 if vacio else cue.relevance(recuerdo)
            if relevancia == 0:
                continue
            valor = relevancia * recuerdo.valor(self._ahora(guardados), self.fade)
            if valor <= 0.0:
                continue
            # `-seq` en la clave: a igualdad de peso gana el más reciente, y el
            # `seq` es único, así que el orden es total y no depende del hash.
            puntuados.append((valor, -recuerdo.seq, recuerdo))

        puntuados.sort(key=lambda x: (-x[0], x[1]))
        return tuple(r for _, _, r in puntuados[:limit])

    def rencor(self, owner: AgentId, tick: int, escala: float) -> dict[ActionId, float]:
        """Cuánto escarmiento arrastra este agente con cada acción. Valores [0, 1).

            rencor[acción] = saturación( Σ |valencia negativa| · valor(hoy),  escala )

        **Es un índice y no una consulta, y esa es la decisión de rendimiento del
        frente.** La deliberación evalúa `len(lugares) * len(acciones)` pares —en
        la ciudad, 800—; llamar a `recall` dentro de ese bucle escanearía la
        memoria entera cada vez, unas 32 000 comparaciones por deliberación, y
        eso hunde el tick. Recorrer los recuerdos UNA vez y consultar un dict
        después es O(capacidad) en lugar de O(pares · capacidad).

        Solo cuenta lo **negativo**. Las alegrías ya están representadas en el
        motor: lo que salió mejor de lo esperado subió `gain_beliefs`, y desde
        ahí ya empuja el beneficio hacia arriba. Sumarlas otra vez aquí sería
        contar dos veces el mismo suceso — el riesgo que este frente tenía que
        esquivar.

        Y por lo mismo, esto NO duplica a `cost_beliefs`. Aquella es la media y
        esta es la cola: un resultado ordinario nunca llega a ser recuerdo, así
        que aquí solo queda lo que se salió de lo normal. La media dice *cuánto
        suele costar esto*; el rencor dice *me acuerdo de la vez que salió fatal*.
        """
        guardados = self._por_duenyo.get(owner)
        if not guardados or escala <= 0.0:
            return {}

        bruto: dict[ActionId, float] = {}
        for recuerdo in guardados:
            if recuerdo.action is None or recuerdo.valencia >= 0.0:
                continue
            peso = -recuerdo.valencia * recuerdo.valor(tick, self.fade)
            if peso > 0.0:
                bruto[recuerdo.action] = bruto.get(recuerdo.action, 0.0) + peso
        return {accion: signed_saturation(v, escala) for accion, v in bruto.items()}

    def miedo(self, owner: AgentId, tick: int, escala: float) -> dict[PlaceId, float]:
        """Cuánto pavor le tiene este agente a cada sitio. Valores [0, 1).

            miedo[lugar] = saturación( Σ |valencia negativa| · valor(hoy),  escala )

        **Hermano exacto de `rencor`, sobre el otro eje.** Aquel penaliza lo que
        HICISTE; este, DÓNDE estabas. Y producen conductas distintas: quien teme
        la plaza no deja de socializar, socializa en otro lado.

        Los dos índices **parten la memoria y no la comparten**, que es como se
        evita contar dos veces el mismo suceso: `rencor` solo mira lo que lleva
        `action`, y este solo lo que no. Un recuerdo es o algo que hiciste o algo
        que te pasó, nunca las dos cosas.

        Y exige `culpable`, que es la línea que hace posible el mecanismo. El
        primer intento de este frente se abandonó justamente aquí: los
        `NEED_CRITICAL` se disparan donde uno esté de pie, así que alimentarse de
        ellos a secas produce miedo a la propia cama. Con el marcador, solo entra
        lo que una situación provocó — el lugar deja de ser *dónde estabas* y
        pasa a ser *parte de por qué*.
        """
        guardados = self._por_duenyo.get(owner)
        if not guardados or escala <= 0.0:
            return {}

        bruto: dict[PlaceId, float] = {}
        for recuerdo in guardados:
            if recuerdo.place is None or recuerdo.action is not None:
                continue
            if recuerdo.culpable is None or recuerdo.valencia >= 0.0:
                continue
            peso = -recuerdo.valencia * recuerdo.valor(tick, self.fade)
            if peso > 0.0:
                bruto[recuerdo.place] = bruto.get(recuerdo.place, 0.0) + peso
        return {lugar: signed_saturation(v, escala) for lugar, v in bruto.items()}

    @staticmethod
    def _ahora(guardados: list[Recuerdo]) -> int:
        """El tick del recuerdo más reciente, como referencia del desdibujado.

        Recuperar no recibe el tick del mundo, y darle uno obligaría a pasar el
        `WorldState` a todo lo que quiera preguntar. Como el desdibujado solo
        importa **en relativo** —cuál pesa más que cuál—, tomar el más reciente
        como presente da exactamente el mismo orden y no acopla nada.
        """
        return guardados[-1].tick if guardados else 0

    # -------------------------------------------------------------------------
    # Persistencia
    # -------------------------------------------------------------------------

    def cargar(self, owner: AgentId, recuerdos: Iterable[Recuerdo]) -> None:
        """Repuebla a un agente al reanudar. Ordena por `seq` porque el olvido y
        `_ahora` dan por hecho que la lista está en orden de ocurrencia."""
        guardados = sorted(recuerdos, key=lambda r: r.seq)
        if guardados:
            self._por_duenyo[owner] = guardados
