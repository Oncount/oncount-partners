"""Helper to call Railway GraphQL API.

Usage:
    python scripts/railway.py project              # show project services & envs
    python scripts/railway.py create-service       # create oncount-partners service from GitHub
    python scripts/railway.py create-postgres      # add Postgres plugin
    python scripts/railway.py vars                 # set env vars (without BOT_TOKEN)
    python scripts/railway.py vars-bot <token>     # set BOT_TOKEN to start bot
    python scripts/railway.py stop-old             # stop old telegram-bot-2brain service
    python scripts/railway.py state                # snapshot of services + variables
"""
import json
import os
import sys
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv()

# Токен НЕ хардкодим (раньше лежал прямо здесь — попал в git-историю, скомпрометирован).
# Берётся только из окружения / .env. Значение — из Railway → Account → Tokens.
TOKEN = os.environ.get("RAILWAY_TOKEN")
if not TOKEN:
    raise SystemExit(
        "RAILWAY_TOKEN не задан. Добавь строку RAILWAY_TOKEN=<токен> в .env "
        "(значение — Railway → Account → Tokens). В код токен не вписывать."
    )
ENDPOINT = "https://backboard.railway.com/graphql/v2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

PROJECT_ID = "bcf7687d-7297-4d05-8a1c-c4279e4e8c1b"  # zippy-inspiration
ENV_ID = "d56b9bc2-3114-4df3-becd-2495a2652c1d"       # production
OLD_SERVICE_ID = "2306a24a-0df7-406e-9645-bce7363e586d"  # worker (telegram-bot-2brain)

GITHUB_REPO = "nikolhillton/oncount-partners"
NEW_SERVICE_NAME = "oncount-partners"


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()}


# ─── queries / mutations ────────────────────────────────────────────────────

Q_PROJECT = """
query($id: String!) {
  project(id: $id) {
    id name
    environments { edges { node { id name } } }
    services { edges { node { id name } } }
  }
}
"""

Q_SERVICES_DETAIL = """
query($id: String!) {
  project(id: $id) {
    services {
      edges {
        node {
          id name
          serviceInstances { edges { node { id environmentId source { repo image } } } }
          deployments(first: 1) { edges { node { id status createdAt } } }
        }
      }
    }
  }
}
"""

Q_VARIABLES = """
query($projectId: String!, $environmentId: String!, $serviceId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
}
"""

M_SERVICE_CREATE_GITHUB = """
mutation($input: ServiceCreateInput!) {
  serviceCreate(input: $input) { id name }
}
"""

M_VARIABLE_UPSERT = """
mutation($input: VariableUpsertInput!) {
  variableUpsert(input: $input)
}
"""

M_DEPLOY = """
mutation($input: ServiceInstanceDeployInput!) {
  serviceInstanceDeployV2(input: $input)
}
"""

M_SERVICE_INSTANCE_UPDATE = """
mutation($environmentId: String!, $serviceId: String!, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(environmentId: $environmentId, serviceId: $serviceId, input: $input)
}
"""

M_DEPLOYMENT_STOP = """
mutation($id: String!) { deploymentStop(id: $id) }
"""


# ─── commands ────────────────────────────────────────────────────────────────


def cmd_project():
    print(json.dumps(gql(Q_PROJECT, {"id": PROJECT_ID}), indent=2, ensure_ascii=False))


def cmd_state():
    print(json.dumps(gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID}), indent=2, ensure_ascii=False))


def cmd_create_service():
    """Create the oncount-partners service from GitHub repo."""
    result = gql(M_SERVICE_CREATE_GITHUB, {
        "input": {
            "projectId": PROJECT_ID,
            "name": NEW_SERVICE_NAME,
            "source": {"repo": GITHUB_REPO},
            "branch": "main",
        }
    })
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_create_postgres():
    """Create Postgres database service."""
    result = gql(M_SERVICE_CREATE_GITHUB, {
        "input": {
            "projectId": PROJECT_ID,
            "name": "postgres",
            "source": {"image": "ghcr.io/railwayapp-templates/postgres-ssl:16"},
        }
    })
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_vars(extra_vars: dict | None = None):
    """Set env vars for the bot service (without BOT_TOKEN by default)."""
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    services = state["data"]["project"]["services"]["edges"]
    bot_service = next((s["node"] for s in services if s["node"]["name"] == NEW_SERVICE_NAME), None)
    if not bot_service:
        print(f"Service {NEW_SERVICE_NAME!r} not found. Run create-service first.")
        return
    sid = bot_service["id"]

    jwt_secret = os.environ.get("JWT_SECRET")
    if not jwt_secret:
        raise SystemExit("JWT_SECRET не задан в .env — секрет не хардкодим в коде.")
    base = {
        "BOT_USERNAME": "community_oncount_bot",
        "JWT_SECRET": jwt_secret,
        "ADMIN_TG_ID": "6634813047",
        "DATABASE_URL": "${{postgres.DATABASE_URL}}",
        "WEBAPP_URL": "https://oncount-partners.up.railway.app",
    }
    if extra_vars:
        base.update(extra_vars)

    for k, v in base.items():
        r = gql(M_VARIABLE_UPSERT, {"input": {
            "projectId": PROJECT_ID,
            "environmentId": ENV_ID,
            "serviceId": sid,
            "name": k,
            "value": v,
        }})
        print(f"{k} → {r}")


def cmd_set_bot_token(token: str):
    cmd_vars({"BOT_TOKEN": token})


def cmd_stop_old():
    """Get latest deployment for the old worker service and stop it."""
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    services = state["data"]["project"]["services"]["edges"]
    old = next((s["node"] for s in services if s["node"]["id"] == OLD_SERVICE_ID), None)
    if not old:
        print("Old service not found.")
        return
    deps = old.get("deployments", {}).get("edges", [])
    if not deps:
        print("No deployments for old service.")
        return
    dep_id = deps[0]["node"]["id"]
    print(f"Stopping deployment {dep_id} of service {old['name']}")
    r = gql(M_DEPLOYMENT_STOP, {"id": dep_id})
    print(json.dumps(r, indent=2, ensure_ascii=False))


# ─── entrypoint ──────────────────────────────────────────────────────────────


COMMANDS = {
    "project": cmd_project,
    "state": cmd_state,
    "create-service": cmd_create_service,
    "create-postgres": cmd_create_postgres,
    "vars": cmd_vars,
    "stop-old": cmd_stop_old,
}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "project"
    if cmd == "vars-bot":
        if len(sys.argv) < 3:
            print("Usage: railway.py vars-bot <BOT_TOKEN>")
            sys.exit(1)
        cmd_set_bot_token(sys.argv[2])
    elif cmd in COMMANDS:
        COMMANDS[cmd]()
    else:
        print(f"Unknown command: {cmd}\nAvailable: {', '.join(list(COMMANDS) + ['vars-bot'])}")
