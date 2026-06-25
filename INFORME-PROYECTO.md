# Informe del proyecto «Agente»

> Documento de resumen para una lectura no técnica. Explica **qué es** el
> proyecto, **qué sabe hacer**, **qué reglas** sigue y **qué límites** tiene, sin
> entrar en cómo está programado.

---

## 1. En una frase

«Agente» es un **asistente de inteligencia artificial autónomo** que recibe una
tarea escrita en lenguaje natural, decide por sí mismo los pasos para
resolverla, usa una serie de **herramientas** (calculadora, búsqueda en
internet, lectura de páginas web, manejo de archivos, programación) y entrega un
resultado final. No es un simple chat: es un agente que **actúa**.

---

## 2. Qué lo diferencia de un chat normal

Un chat responde de un solo golpe con lo que «sabe». Este agente, en cambio,
trabaja en un **ciclo de pensar → actuar → comprobar**:

1. **Interpreta** la petición y, si es compleja, la divide en pasos.
2. En cada paso **decide si necesita una herramienta** (por ejemplo, buscar en
   internet o leer un archivo) y la utiliza.
3. **Observa el resultado** y lo usa para decidir el siguiente paso.
4. Repite hasta tener suficiente información y entonces da una **respuesta final
   completa**.

Esto le permite resolver tareas que requieren información actualizada, cálculos
o acciones sobre el ordenador, no solo conversar.

---

## 3. Qué puede hacer el agente (capacidades)

El agente dispone de un conjunto de herramientas. Según la tarea, elige cuáles
usar:

| Herramienta | Qué permite hacer | Ejemplo de tarea |
|-------------|-------------------|------------------|
| **Calculadora** | Resolver operaciones matemáticas de forma exacta y segura. | «¿Cuánto es (12² + 8) / 4?» |
| **Búsqueda web** | Buscar en internet para localizar páginas relevantes. | «Encuentra la web oficial de X.» |
| **Lectura de páginas web** | Leer el contenido real de una página concreta (artículos, fichas de producto, precios). | «Dime el precio que aparece en esta URL.» |
| **Navegador web** | Leer páginas más complejas que requieren un navegador (opcional). | Webs que cargan contenido dinámicamente. |
| **Archivos** | Leer, escribir, listar y buscar archivos en el ordenador. | «Guarda el resultado en un archivo de texto.» |
| **Programación (Claude Code)** | Delegar tareas de programación a un agente especializado: crear código, hacer cambios, escribir pruebas, depurar. | «Crea un programa que haga X y su prueba.» |

**Idea clave:** el agente combina varias herramientas en una misma tarea. Por
ejemplo, puede buscar en internet, leer la página encontrada, hacer un cálculo
con esos datos y guardar el resultado en un archivo, todo de forma encadenada y
autónoma.

---

## 4. Cómo se usa (formas de interacción)

El proyecto ofrece tres maneras de utilizar el mismo agente:

- **Línea de comandos:** se le pasa la tarea directamente como texto y devuelve
  la respuesta. También tiene un **modo interactivo** tipo conversación.
- **Interfaz visual en la terminal (TUI):** una pantalla completa con un panel de
  conversación y un panel lateral que muestra el modelo en uso, las herramientas
  disponibles, el consumo y la **traza** de cada respuesta (qué pasos y qué
  herramientas se usaron). Permite ver «cómo piensa» el agente.
- **Como componente de software:** otros programas pueden integrarlo y pedirle
  tareas mediante un punto de entrada estable.

**Comando especial:** escribiendo `/claude` antes de una petición, el usuario
puede **forzar** que la tarea se delegue al agente de programación. Si esa
capacidad no está disponible, la orden se ignora y la tarea sigue el curso
normal.

---

## 5. Reglas de comportamiento del agente

El agente sigue unas normas internas de trabajo:

- **No inventa datos:** si necesita un cálculo, usa la calculadora; si necesita
  información que no conoce o que pudo cambiar, la busca en internet en lugar de
  suponerla.
- **No se repite:** no vuelve a hacer la misma acción con los mismos datos si ya
  tiene el resultado.
- **Se recupera de los errores:** si una herramienta falla, analiza el problema y
  reintenta con otro enfoque, en vez de bloquearse.
- **Sabe cuándo parar:** cuando tiene información suficiente, entrega la respuesta
  final sin seguir consumiendo recursos.
- **Es conciso al razonar y completo al responder.**

---

## 6. Reglas de seguridad (lo que NO puede hacer)

La seguridad es un pilar del diseño, sobre todo en el acceso a archivos:

- **Acceso limitado por defecto (modo «scoped»):** el agente solo puede tocar la
  carpeta de trabajo actual y sus subcarpetas. No puede salir de ahí.
- **Acceso total opcional (modo «system»):** se activa de forma explícita al
  arrancar con una opción especial (`-dap`). Da acceso a todo el ordenador,
  **salvo carpetas delicadas del sistema** que quedan siempre bloqueadas (en
  Windows: `C:\Windows`, `Archivos de programa`, papelera, recuperación, etc.; y
  las equivalentes en Linux/Mac).
- **Secretos siempre protegidos:** en **ambos** modos, el agente tiene prohibido
  leer archivos sensibles como claves de acceso, contraseñas o ficheros de
  credenciales. Así no puede leer ni su propia clave ni las del usuario.
- **A prueba de trucos:** los bloqueos no se pueden esquivar con rutas
  engañosas ni atajos del sistema de archivos.

> En resumen: por defecto el agente está «encerrado» en una carpeta y no puede
> ver secretos. El acceso amplio es una decisión consciente del usuario, con
> advertencias claras.

---

## 7. Control de coste y límites

Un agente que razona, reintenta y reenvía contexto **consume más** que un chat de
un solo turno. El proyecto incorpora controles:

- **Límite de pasos por tarea:** evita que el agente entre en bucles
  interminables.
- **Detección de bucles:** si repite la misma acción varias veces, se detiene.
- **Medición de consumo:** cada resultado informa de cuántos «tokens» (unidad de
  consumo del modelo) se usaron, para poder medir el gasto.
- **La herramienta de programación es la más cara** y está acotada por un máximo
  de turnos y un **presupuesto en dólares** por invocación.

---

## 8. Requisitos funcionales (resumen)

Lo que el sistema **debe** ofrecer:

1. Aceptar tareas en lenguaje natural y resolverlas de forma autónoma.
2. Decidir y usar las herramientas adecuadas en cada paso.
3. Mantener una **conversación con memoria** dentro de una misma sesión.
4. Ofrecer al menos tres formas de uso (comandos, interfaz visual e integración).
5. Permitir forzar la herramienta de programación con `/claude`.
6. Respetar el modelo de seguridad de archivos (acceso limitado por defecto,
   protección de secretos siempre).
7. Acotar y medir el coste de cada tarea.
8. Ser configurable (modelo a usar, límites, qué herramientas activar) sin
   necesidad de cambiar el programa.

---

## 9. Cómo está organizado (visión de alto nivel)

Sin entrar en detalle técnico, el proyecto está construido de forma **modular**,
con una idea central: el «cerebro» del agente es **independiente** del proveedor
de inteligencia artificial y de la forma de usarlo.

- El **núcleo** decide y coordina, pero no sabe qué proveedor de IA hay detrás ni
  por qué pantalla se le habla.
- Las **herramientas** son piezas intercambiables: se pueden añadir nuevas sin
  cambiar el núcleo.
- Las **interfaces** (comandos, pantalla visual) son capas finas que se apoyan en
  el mismo cerebro.

**Ventaja práctica:** se puede **cambiar el modelo de IA**, **añadir herramientas
nuevas** o **crear otra forma de uso** (por ejemplo, una web) sin rehacer el
proyecto. Está pensado para crecer.

---

## 10. Estado actual y límites conocidos

- La **memoria de la conversación es temporal:** vive mientras el programa está
  abierto; no se guarda entre sesiones (está preparado para añadir guardado
  permanente en el futuro).
- La **búsqueda web básica** ofrece resultados limitados; para un uso profesional
  se podría sustituir por un proveedor más potente.
- Algunas capacidades (navegador web, programación) son **opcionales** y
  requieren instalación adicional; el agente las activa automáticamente solo si
  están disponibles.
- El proveedor de IA por defecto es **MiniMax**, pero es sustituible.

---

## 11. Conclusión

«Agente» es una base sólida y segura para un asistente de IA que **no solo
responde, sino que actúa**: busca, lee, calcula, gestiona archivos y hasta
programa, encadenando herramientas de forma autónoma. Destaca por su **diseño
modular** (fácil de ampliar y de cambiar de proveedor), su **modelo de seguridad
cuidadoso** (acceso limitado y protección de secretos) y su **control del coste**.
Sus límites actuales —memoria temporal y búsqueda web básica— son conscientes y
están preparados para evolucionar.
