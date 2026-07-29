### tuning

| perilla | valor |
|---|---|
| `travel_discount` | 0.93 |
| `candidate_pool` | 3 |
| `temperature` | 0.12 |
| `loss_aversion` | 1.0 |
| `critical_need_threshold` | 0.15 |

### needs

| id | decay | initial | base_weight | urgency_exp | vacía en |
|---|---|---|---|---|---|
| `sustento` | 0.007 | 0.75 | 1.0 | 2.5 | 36 h |
| `descanso` | 0.007 | 0.85 | 1.0 | 2.2 | 36 h |
| `dinero` | 0.0008 | 0.55 | 0.9 | 1.6 | 312 h |
| `vinculo` | 0.004 | 0.6 | 0.75 | 1.9 | 62 h |
| `estimulo` | 0.004 | 0.55 | 0.65 | 1.7 | 62 h |
| `provisiones` | 0.0012 | 0.7 | 0.5 | 1.4 | 208 h |

### traits

| id | pesos de necesidad | temperamento |
|---|---|---|
| `sociabilidad` | `vinculo`×2.2, `descanso`×0.9 | — |
| `laboriosidad` | `dinero`×1.6, `descanso`×0.75 | — |
| `hedonismo` | `estimulo`×2.4, `dinero`×0.7 | — |
| `frugalidad` | `dinero`×1.5, `provisiones`×1.6, `estimulo`×0.6 | — |
| `apego_al_hogar` | `descanso`×1.35, `vinculo`×0.7 | — |
| `impulsividad` | — | `temperature`×3.0, `loss_aversion`×0.55 |
| `aguante` | — | `critical_need_threshold`×0.6 |
| `arraigo` | — | `travel_discount`×0.8 |

### actions

| id | dur | affordance | satisfies | costs | effects |
|---|---|---|---|---|---|
| `dormir` | 30 | `lecho` | descanso +1.00 | — | descanso +0.95 |
| `descansar` | 8 | `lecho` | descanso +0.40, estimulo +0.15 | — | descanso +0.30, estimulo +0.08 |
| `cocinar` | 6 | `cocina` | sustento +0.90 | provisiones +0.45, dinero +0.05 | sustento +0.72, provisiones -0.22, dinero -0.01 |
| `comer_fuera` | 5 | `mesa` | sustento +1.00, vinculo +0.20 | dinero +0.50 | sustento +0.85, dinero -0.09, vinculo +0.08 |
| `hacer_compras` | 7 | `comercio` | provisiones +1.00 | dinero +0.40 | provisiones +0.75, dinero -0.12 |
| `darse_un_capricho` | 5 | `capricho` | estimulo +0.70 | dinero +0.55 | estimulo +0.45, dinero -0.16 |
| `trabajar_en_oficina` | 32 | `labor_administrativa` | dinero +1.00 | descanso +0.28, sustento +0.20 | dinero +0.33, descanso -0.16, sustento -0.10, vinculo +0.05 |
| `trabajar_en_taller` | 28 | `labor_taller` | dinero +0.90 | descanso +0.38, sustento +0.24 | dinero +0.29, descanso -0.22, sustento -0.12 |
| `trabajar_en_almacen` | 24 | `labor_almacen` | dinero +0.80 | descanso +0.48, sustento +0.26 | dinero +0.24, descanso -0.26, sustento -0.13 |
| `charlar` | 6 | `tertulia` | vinculo +1.00 | descanso +0.10 | vinculo +0.55, estimulo +0.10, descanso -0.03 |
| `salir_de_fiesta` | 14 | `jolgorio` | estimulo +1.00, vinculo +0.60 | dinero +0.75, descanso +0.60 | estimulo +0.80, vinculo +0.35, descanso -0.30, dinero -0.20 |
| `tomar_el_aire` | 6 | `aire_libre` | estimulo +0.45, descanso +0.15 | — | estimulo +0.28, descanso +0.05 |
| `holgazanear` | 4 | — | descanso +0.12 | — | descanso +0.04 |

### pesos compuestos por agente

| agente | sustento | descanso | dinero | vinculo | estimulo | provisiones |
|---|---|---|---|---|---|---|
| **Alexia** | 1.000 | 0.715 | 0.727 | 2.028 | 1.099 | 0.500 |
| **Karla** | 1.000 | 1.328 | 1.245 | 0.336 | 0.432 | 0.728 |
| **Kiara** | 1.000 | 0.949 | 0.489 | 1.112 | 1.970 | 0.343 |
| **Linda** | 1.000 | 1.284 | 1.086 | 0.268 | 0.650 | 0.500 |
| **Samantha** | 1.000 | 0.745 | 0.653 | 1.809 | 1.429 | 0.500 |
| **Jack** | 1.000 | 1.084 | 0.639 | 1.204 | 0.845 | 0.500 |
| **Leonardo** | 1.000 | 0.820 | 1.672 | 0.592 | 0.478 | 0.663 |
| **Arden** | 1.000 | 0.919 | 2.160 | 0.359 | 0.273 | 0.632 |
| **Corin** | 1.000 | 1.042 | 0.581 | 1.302 | 1.200 | 0.500 |
| **Tym** | 1.000 | 1.198 | 1.950 | 0.300 | 0.255 | 0.728 |

### temperamento compuesto por agente

| agente | temperature | loss_aversion | critical_threshold | travel_discount |
|---|---|---|---|---|
| **Alexia** | 0.2589 | 0.658 | 0.1500 | 1.0000 |
| **Karla** | 0.0621 | 1.431 | 0.1500 | 0.8135 |
| **Kiara** | 0.2320 | 0.699 | 0.1162 | 0.9300 |
| **Linda** | 0.0556 | 1.520 | 0.1500 | 0.7780 |
| **Samantha** | 0.3225 | 0.584 | 0.1500 | 1.0000 |
| **Jack** | 0.1495 | 0.887 | 0.1287 | 0.9300 |
| **Leonardo** | 0.0446 | 1.713 | 0.1049 | 0.9300 |
| **Arden** | 0.0498 | 1.613 | 0.0997 | 0.8135 |
| **Corin** | 0.2078 | 0.742 | 0.1500 | 1.0000 |
| **Tym** | 0.0556 | 1.520 | 0.1104 | 0.7955 |

### distancias desde el vestíbulo (ticks)

| destino | ticks | descuento a 0.93 |
|---|---|---|
| el vestíbulo del edificio | 0 | 1.0000 |
| la habitación 1 | 1 | 0.9300 |
| la plaza | 1 | 0.9300 |
| el café | 2 | 0.8649 |
| el club nocturno | 4 | 0.7481 |
| el mercado | 3 | 0.8044 |
| el bazar | 3 | 0.8044 |
| la fonda | 2 | 0.8649 |
| el restaurante | 3 | 0.8044 |
| la oficina | 3 | 0.8044 |
| el taller | 5 | 0.6957 |
| el almacén | 5 | 0.6957 |