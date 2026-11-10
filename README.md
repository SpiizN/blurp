# Burp Community avec Reburp et MCP

Cette stack lance Burp Suite Community Edition 2026.10.1, charge Reburp 1.1.15 et expose un serveur MCP Streamable HTTP sur `http://127.0.0.1:8765/mcp`. Le serveur lit la spécification OpenAPI de Reburp en direct et donne accès à ses 206 opérations avec quatre outils MCP.

```text
Agent -> 127.0.0.1:8765/mcp -> serveur MCP -> 127.0.0.1:9090/api -> Burp Community
```

Le conteneur MCP partage le réseau du conteneur Burp, car Reburp n'écoute que sur `127.0.0.1:9090`. Le port 9090 n'est pas publié sur l'hôte. Burp utilise un affichage Xvfb interne pour franchir ses écrans de démarrage, sans interface graphique exposée.

## Démarrage

Prérequis : Docker avec Compose et environ 4 Go de mémoire disponibles pour la stack.

1. Lisez les [conditions d'utilisation de PortSwigger](https://portswigger.net/burp/eula), notamment l'addendum D pour Community Edition.
2. Copiez `.env.example` vers `.env`. Mettez `BURP_ACCEPT_EULA=true` si vous acceptez ces conditions et renseignez `MCP_BEARER_TOKEN` avec au moins 32 caractères aléatoires, par exemple la sortie de `openssl rand -hex 32`. Protégez le fichier avec `chmod 600 .env`.
3. Lancez la stack :

   ```sh
   docker compose up -d --build
   ```

4. Vérifiez les deux services :

   ```sh
   docker compose ps
   docker compose exec burp curl -fsS http://127.0.0.1:9090/api/status
   ```

Le premier build télécharge les JAR officiels de Burp et de Reburp et vérifie leurs empreintes SHA-256. Le premier démarrage peut prendre quelques dizaines de secondes. `docker compose down` arrête la stack et conserve les préférences Burp dans le volume `burp-home`.

## Connexion d'un agent

Configurez votre client MCP pour utiliser l'URL `http://127.0.0.1:8765/mcp` avec le transport Streamable HTTP et l'en-tête `Authorization: Bearer <MCP_BEARER_TOKEN>`, en prenant la valeur dans `.env`. Le même en-tête est requis par `/health`. Les outils disponibles sont :

| Outil | Usage |
| --- | --- |
| `status` | Vérifier la version et l'édition de Burp et de Reburp. |
| `search_operations` | Chercher une opération par mot-clé ou tag, avec pagination. |
| `describe_operation` | Lire les paramètres, les schémas JSON et les exemples d'une opération. |
| `call_operation` | Appeler une opération par son `operationId` avec ses paramètres et son corps JSON. |

Flux conseillé : cherchez une opération, consultez sa description, puis appelez-la avec les champs indiqués par la spécification. Par exemple, `search_operations(query="proxy history")`, puis `describe_operation(operation_id="getProxyHistory")`, puis `call_operation(operation_id="getProxyHistory", query_parameters={"limit": 10})`.

`call_operation` renvoie le code HTTP, le type de contenu et le corps de la réponse. Les réponses binaires sont encodées en Base64. Une erreur HTTP de Reburp reste visible avec son code et son corps ; les erreurs de transport nomment l'opération concernée.

## Limites et accès

Burp Community n'inclut pas les fonctions réservées à Professional. Les opérations Scanner, Collaborator et AI peuvent répondre `403`. Les projets Community sont temporaires en mémoire : les préférences Burp persistent dans le volume, mais l'historique de trafic ne survit pas à un redémarrage.

Le MCP exige le bearer token et n'est publié que sur la boucle locale de l'hôte. Gardez le token secret, conservez cette liaison locale et n'appelez les opérations générant du trafic que sur des cibles que vous êtes autorisé à tester. L'exécuteur shell de Reburp est désactivé par défaut.

Versions et contrats : [Burp 2026.10.1](https://portswigger.net/burp/releases/professional-community-2026-10-1), [Reburp 1.1.15](https://github.com/forefy/reburp/releases/tag/v1.1.15), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
