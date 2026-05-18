"""Fetch last deployment logs for a service."""
import json
import sys
import urllib.request
import urllib.error

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, Q_SERVICES_DETAIL, TOKEN, ENDPOINT, UA  # noqa: E402


Q_LOGS = """
query($deploymentId: String!, $limit: Int!) {
  deploymentLogs(deploymentId: $deploymentId, limit: $limit) {
    message timestamp severity
  }
}
"""

Q_BUILD_LOGS = """
query($deploymentId: String!, $limit: Int!) {
  buildLogs(deploymentId: $deploymentId, limit: $limit) {
    message timestamp severity
  }
}
"""


def latest_deployment(name: str) -> str | None:
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    for e in state["data"]["project"]["services"]["edges"]:
        n = e["node"]
        if n["name"] == name:
            deps = n.get("deployments", {}).get("edges", [])
            if deps:
                return deps[0]["node"]["id"]
    return None


def main(name: str, which: str = "deploy"):
    dep_id = latest_deployment(name)
    if not dep_id:
        print(f"No deployment for {name}")
        return
    q = Q_LOGS if which == "deploy" else Q_BUILD_LOGS
    r = gql(q, {"deploymentId": dep_id, "limit": 200})
    if "errors" in r:
        print(json.dumps(r, indent=2))
        return
    key = "deploymentLogs" if which == "deploy" else "buildLogs"
    for line in r["data"][key]:
        print(f"[{line.get('severity','-'):5s}] {line.get('timestamp','')} {line.get('message','')}")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "postgres"
    which = sys.argv[2] if len(sys.argv) > 2 else "deploy"
    main(name, which)
