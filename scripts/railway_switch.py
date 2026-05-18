"""Final switch:
1. Stop old `worker` deployment (telegram-bot-2brain).
2. Add BOT_TOKEN to oncount-partners env.
3. Trigger build of latest commit on oncount-partners.
"""
import subprocess
import sys

sys.path.insert(0, ".")
from scripts.railway import (  # noqa: E402
    gql, PROJECT_ID, ENV_ID,
    M_VARIABLE_UPSERT, M_DEPLOYMENT_STOP,
    Q_SERVICES_DETAIL,
)

BOT_TOKEN = "8368308511:AAEBnyB59RNXTLG70yb8ijoOS3HXLE3QFGk"

M_DEPLOY_SHA = """
mutation($serviceId: String!, $environmentId: String!, $commitSha: String) {
  serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId, commitSha: $commitSha)
}
"""


def find_services():
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    out = {}
    for e in state["data"]["project"]["services"]["edges"]:
        out[e["node"]["name"]] = e["node"]
    return out


def main():
    services = find_services()
    old = services["worker"]
    new = services["oncount-partners"]

    # 1. Stop old worker (telegram-bot-2brain)
    print("\n[1] Stop old worker (telegram-bot-2brain)")
    deps = old.get("deployments", {}).get("edges", [])
    if deps:
        dep_id = deps[0]["node"]["id"]
        r = gql(M_DEPLOYMENT_STOP, {"id": dep_id})
        print(f"  deploymentStop({dep_id}): {r}")
    else:
        print("  no active deployment")

    # 2. Set BOT_TOKEN in oncount-partners
    print("\n[2] Set BOT_TOKEN in oncount-partners")
    r = gql(M_VARIABLE_UPSERT, {"input": {
        "projectId": PROJECT_ID,
        "environmentId": ENV_ID,
        "serviceId": new["id"],
        "name": "BOT_TOKEN",
        "value": BOT_TOKEN,
    }})
    print(f"  BOT_TOKEN -> {r}")

    # 3. Trigger build of latest local SHA
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    print(f"\n[3] Trigger build of {sha} on oncount-partners")
    r = gql(M_DEPLOY_SHA, {
        "serviceId": new["id"],
        "environmentId": ENV_ID,
        "commitSha": sha,
    })
    print(f"  serviceInstanceDeployV2: {r}")


if __name__ == "__main__":
    main()
