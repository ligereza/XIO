# Adaptador XIO

Esta carpeta define una frontera, no una copia del runtime de XIO.

## Permitido

- recibir observaciones del servidor/controlador de XIO como `Event`;
- entregar resultados de una `ExplicitAction` a través del `ActionGate`;
- conectar más adelante una implementación concreta mediante dependencias
  inyectadas.

## Fuera de XIO Layer

- Android, HyperOS, Termux, Termux:Boot y Termux:API;
- ADB, Shizuku y rish;
- los 32 plugins Xiaomi y sus permisos concretos;
- hotspot, radio, batería, USB, pantalla y sensores específicos;
- showcontrol, Art-Net, OSC, timecode y la lógica de shows;
- cualquier bridge o lógica específica de MAK.

No hay imports de esos runtimes en el adaptador. Eso evita que el núcleo
reutilizable quede atado a un teléfono concreto y evita que una observación
pueda ejecutar algo por sí sola.
