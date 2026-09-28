# Agente conversacional (n8n)

Agente de IA que responde en lenguaje natural preguntas como «¿qué clientes están críticos?» con las mismas cifras del
tablero. No calcula ni inventa números: los consulta en la API de solo lectura de la aplicación (`/api/agente/`).

## Cómo ejecutarlo

1. En n8n: *Import from File* y elija `agente_siniestralidad.json`.
2. Cree las credenciales que pide cada nodo: OpenAI (modelo), *Header Auth* con `Authorization: Bearer <token>`
   (herramientas) y *Basic Auth* (chat).
3. Publique el flujo.

El token se crea en el servidor con `python manage.py crear_token_agente --usuario agente_n8n --nombre n8n`. Para que
el chat aparezca en la aplicación, configure en el servidor `AGENTE_CHAT_URL`, `AGENTE_CHAT_USUARIO` y
`AGENTE_CHAT_CLAVE`.
