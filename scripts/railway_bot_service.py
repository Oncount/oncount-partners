"""Create oncount-partners-bot service, set startCommand + env vars + BOT_TOKEN."""
import json
import sys

sys.path.insert(0, ".")
from scripts.railway import (  # noqa: E402
    gql, PROJECT_ID, ENV_ID,
    M_SERVICE_CREATE_GITHUB, M_VARIABLE_UPSERT,
    Q_SERVICES_DETAIL,
)

BOT_TOKEN = "8368308511:AAEBnyB59RNXTLG70yb8ijoOS3HXLE3QFGk"
NEW_NAME = "oncount-partners-bot"
START_COMMAND = "python -m app.bot"

M_INSTANCE_UPDATE = """
mutation($environmentId: String!, $serviceId: String!, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(environmentId: $environmentId, serviceId: $serviceId, input: $input)
}
"""


def find(name: str):
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    for e in state["data"]["project"]["services"]["edges"]:
        if e["node"]["name"] == name:
            return e["node"]
    return None


def upsert_var(sid: str, name: str, value: str):
    r = gql(M_VARIABLE_UPSERT, {"input": {
        "projectId": PROJECT_ID,
        "environmentId": ENV_ID,
        "serviceId": sid,
        "name": name,
        "value": value,
    }})
    print(f"  {name} -> {r.get('data') or r}")


def main():
    # 1. Skip create if already exists
    existing = find(NEW_NAME)
    if existing:
        print(f"Service {NEW_NAME} already exists: {existing['id']}")
        sid = existing["id"]
    else:
        r = gql(M_SERVICE_CREATE_GITHUB, {"input": {
            "projectId": PROJECT_ID,
            "name": NEW_NAME,
            "source": {"repo": "nikolhillton/oncount-partners"},
            "branch": "main",
        }})
        print("[1] serviceCreate:", json.dumps(r, ensure_ascii=False))
        sid = r["data"]["serviceCreate"]["id"]

    # 2. set startCommand
    r = gql(M_INSTANCE_UPDATE, {
        "environmentId": ENV_ID,
        "serviceId": sid,
        "input": {"startCommand": START_COMMAND},
    })
    print(f"[2] startCommand={START_COMMAND}:", r)

    # 3. copy env from web service + BOT_TOKEN
    web = find("oncount-partners")
    db_url = (
        "postgresql+psycopg2://oncount:aS0NXdrozYYIuSXPsZMxZOUUcZKVDSZT"
        "@postgres.railway.internal:5432/oncount_partners"
    )
    env_vars = {
        "BOT_TOKEN": BOT_TOKEN,
        "BOT_USERNAME": "community_oncount_bot",
        "ADMIN_TG_ID": "6634813047",
        "DATABASE_URL": db_url,
        "WEBAPP_URL": "https://oncount-partners-production.up.railway.app",
        "JWT_SECRET": "shared-secret-not-used-by-bot-process-but-required-by-config",
    }
    print(f"[3] env vars for {NEW_NAME}:")
    for k, v in env_vars.items():
        upsert_var(sid, k, v)

    print(f"\nService id: {sid}")
    print("Ready. Railway will trigger build automatically after env/startCommand change.")


if __name__ == "__main__":
    main()
