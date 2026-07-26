"""Topología del grafo de lugares: rutas, distancias y navegabilidad.

Todo se precomputa una vez al cargar el pack. Con decenas de lugares el coste
es despreciable y a cambio cada consulta durante la simulación es O(1). Un
agente que decide su acción consulta distancias a *todos* los lugares en cada
deliberación: hacerlo con Dijkstra en caliente sería el cuello de botella del
tick loop.

El grafo es **dirigido a propósito**: bajar un acantilado puede costar menos
que subirlo, y una puerta puede abrir en un solo sentido.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping

from agora.engine.ontology import PlaceId, PlaceSpec

INFINITE = 1 << 30
"""Centinela de "inalcanzable". Entero grande en vez de math.inf para que las
distancias sigan siendo `int` y no se cuelen floats en el motor."""


def _reachable(adjacency: Mapping[PlaceId, Iterable[PlaceId]], origin: PlaceId) -> set[PlaceId]:
    """Recorrido en anchura ignorando pesos: solo importa si se llega."""
    seen = {origin}
    queue = deque([origin])
    while queue:
        for neighbor in adjacency.get(queue.popleft(), ()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def is_strongly_connected(places: Iterable[PlaceSpec]) -> bool:
    """¿Puede cualquier agente ir de cualquier lugar a cualquier otro?

    En un grafo dirigido no basta con que "todo esté conectado". Si existe
    `campo -> plaza` pero no `plaza -> campo`, un agente entra al campo y se
    queda varado el resto de la partida. Eso es conexidad *débil* y no sirve.

    Verificarlo es más barato de lo que parece: un grafo dirigido es
    fuertemente conexo si, desde un nodo cualquiera, se alcanza todo el grafo
    hacia adelante **y** también hacia atrás (recorriendo las aristas
    invertidas). Dos BFS, no uno por cada par de nodos.
    """
    catalog = list(places)
    if len(catalog) <= 1:
        return True

    forward: dict[PlaceId, list[PlaceId]] = {p.id: list(p.neighbors) for p in catalog}
    backward: dict[PlaceId, list[PlaceId]] = {p.id: [] for p in catalog}
    for place in catalog:
        for neighbor in place.neighbors:
            if neighbor in backward:
                backward[neighbor].append(place.id)

    total = len(catalog)
    root = catalog[0].id
    return len(_reachable(forward, root)) == total and len(_reachable(backward, root)) == total


class TravelMap:
    """Distancias y primeros pasos entre todos los pares de lugares.

    Se construye con Floyd-Warshall: O(V^3) una sola vez al cargar. Para el
    tamaño de un mundo jugable (decenas de lugares) es instantáneo, y evita
    tener que decidir después dónde cachear rutas.

    Guarda también el *primer salto* de cada ruta óptima. Un agente que viaja
    no necesita la ruta entera: solo hacia dónde moverse ahora. Recalcular el
    primer salto en cada llegada hace que los desvíos futuros (un camino
    cortado, un lugar cerrado de noche) se absorban solos.
    """

    __slots__ = ("_distance", "_first_hop", "_places")

    def __init__(self, places: Iterable[PlaceSpec]) -> None:
        catalog = list(places)
        self._places: tuple[PlaceId, ...] = tuple(p.id for p in catalog)

        distance: dict[PlaceId, dict[PlaceId, int]] = {
            a: {b: (0 if a == b else INFINITE) for b in self._places} for a in self._places
        }
        first_hop: dict[PlaceId, dict[PlaceId, PlaceId | None]] = {
            a: dict.fromkeys(self._places, None) for a in self._places
        }

        for place in catalog:
            for neighbor, cost in place.neighbors.items():
                # Aristas paralelas declaradas dos veces: gana la más barata.
                if cost < distance[place.id][neighbor]:
                    distance[place.id][neighbor] = cost
                    first_hop[place.id][neighbor] = neighbor

        for via in self._places:
            for start in self._places:
                if distance[start][via] == INFINITE:
                    continue  # poda: sin ruta hasta el intermedio, no hay nada que mejorar
                for goal in self._places:
                    candidate = distance[start][via] + distance[via][goal]
                    if candidate < distance[start][goal]:
                        distance[start][goal] = candidate
                        # El primer paso hacia `goal` es el mismo que hacia `via`.
                        first_hop[start][goal] = first_hop[start][via]

        self._distance = distance
        self._first_hop = first_hop

    @property
    def places(self) -> tuple[PlaceId, ...]:
        return self._places

    def distance(self, origin: PlaceId, destination: PlaceId) -> int:
        """Ticks de viaje por la ruta más corta. `INFINITE` si no hay ruta."""
        return self._distance[origin][destination]

    def is_reachable(self, origin: PlaceId, destination: PlaceId) -> bool:
        return self._distance[origin][destination] < INFINITE

    def first_hop(self, origin: PlaceId, destination: PlaceId) -> PlaceId | None:
        """Siguiente lugar al que moverse. `None` si ya está o no hay ruta."""
        if origin == destination:
            return None
        return self._first_hop[origin][destination]

    def route(self, origin: PlaceId, destination: PlaceId) -> list[PlaceId]:
        """Ruta completa sin el origen. Vacía si no hay camino.

        El motor no la necesita (le basta `first_hop`), pero es imprescindible
        para depurar y para que el narrador pueda describir un trayecto.
        """
        if not self.is_reachable(origin, destination):
            return []

        path: list[PlaceId] = []
        current = origin
        while current != destination:
            step = self._first_hop[current][destination]
            if step is None:  # pragma: no cover - imposible si is_reachable pasó
                return []
            path.append(step)
            current = step
        return path
