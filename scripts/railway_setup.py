"""Wire up Postgres + oncount-partners on Railway after services are created.

1. Set Postgres env (POSTGRES_USER/PASSWORD/DB) so it starts.
2. Create public domain for oncount-partners web.
3. Set oncount-partners env vars (without BOT_TOKEN — to keep old bot alive).
"""
import json
import secrets
import string
import sys

sys.path.insert(0, ".")
from scripts.railway import (  # noqa: E402
    gql,
    PROJECT_ID, ENV_ID,
    M_VARIABLE_UPSERT, Q_SERVICES_DETAIL,
)

POSTGRES_USER = "oncount"
POSTGRES_DB = "oncount_partners"
POSTGRES_PASSWORD = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

POSTGRES_VARS = {
    "POSTGRES_USER": POSTGRES_USER,
    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
    "POSTGRES_DB": POSTGRES_DB,
    "PGDATA": "/var/lib/postgresql/data/pgdata",
}

M_DOMAIN_CREATE = """
mutation($input: ServiceDomainCreateInput!) {
  serviceDomainCreate(input: $input) { domain }
}
"""


def find_services():
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    out = {}
    for e in state["data"]["project"]["services"]["edges"]:
        out[e["node"]["name"]] = e["node"]
    return out


def upsert(sid: str, name: str, value: str) -> None:
    r = gql(M_VARIABLE_UPSERT, {"input": {
        "projectId": PROJECT_ID,
        "environmentId": ENV_ID,
        "serviceId": sid,
        "name": name,
        "value": value,
    }})
    print(f"  {name} -> {r.get('data') or r}")


def main():
    services = find_services()
    pg = services["postgres"]
    bot = services["oncount-partners"]

    print(f"\n[1/3] Set postgres env vars (POSTGRES_USER={POSTGRES_USER}, DB={POSTGRES_DB})")
    for k, v in POSTGRES_VARS.items():
        upsert(pg["id"], k, v)

    print(f"\n[2/3] Create public domain for oncount-partners")
    instance = bot["serviceInstances"]["edges"][0]["node"]
    d = gql(M_DOMAIN_CREATE, {"input": {
        "environmentId": instance["environmentId"],
        "serviceId": bot["id"],
        "targetPort": 8000,
    }})
    print("  ->", json.dumps(d, ensure_ascii=False))
    domain = None
    if d.get("data") and d["data"].get("serviceDomainCreate"):
        domain = d["data"]["serviceDomainCreate"]["domain"]
        webapp_url = f"https://{domain}"
    else:
        webapp_url = "https://oncount-partners.up.railway.app"
    print(f"  Using WEBAPP_URL={webapp_url}")

    print(f"\n[3/3] Set oncount-partners env vars (WITHOUT BOT_TOKEN)")
    db_url = (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@postgres.railway.internal:5432/{POSTGRES_DB}"
    )
    bot_vars = {
        "BOT_USERNAME": "community_oncount_bot",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "ADMIN_TG_ID": "6634813047",
        "DATABASE_URL": db_url,
        "WEBAPP_URL": webapp_url,
        # BOT_TOKEN intentionally NOT set yet — keeps old bot alive
    }
    for k, v in bot_vars.items():
        upsert(bot["id"], k, v)

    print("\nDone.\n")
    print(f"Postgres password (save in credentials.md): {POSTGRES_PASSWORD}")
    print(f"WEBAPP_URL: {webapp_url}")


if __name__ == "__main__":
    main()
