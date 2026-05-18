"""Fetch logs with larger limit + filter."""
import sys, json

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, Q_SERVICES_DETAIL  # noqa: E402

Q = """
query($deploymentId: String!, $limit: Int!, $startDate: DateTime) {
  deploymentLogs(deploymentId: $deploymentId, limit: $limit, startDate: $startDate) {
    message timestamp severity
  }
}
"""


def main(name: str):
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    for e in state["data"]["project"]["services"]["edges"]:
        n = e["node"]
        if n["name"] == name:
            deps = n.get("deployments", {}).get("edges", [])
            if deps:
                dep_id = deps[0]["node"]["id"]
                r = gql(Q, {"deploymentId": dep_id, "limit": 500})
                if "errors" in r:
                    print(json.dumps(r, indent=2))
                    return
                for line in r["data"]["deploymentLogs"]:
                    msg = line.get("message", "")
                    print(f"[{line.get('severity','-'):5s}] {line.get('timestamp','')} {msg}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "oncount-partners")
