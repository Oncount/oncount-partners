"""Trigger redeploy of a service by name."""
import sys

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, ENV_ID, Q_SERVICES_DETAIL  # noqa: E402

M_REDEPLOY = """
mutation($serviceId: String!, $environmentId: String!) {
  serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId)
}
"""


def main(name: str):
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    target = None
    for e in state["data"]["project"]["services"]["edges"]:
        if e["node"]["name"] == name:
            target = e["node"]
            break
    if not target:
        print(f"Service not found: {name}")
        sys.exit(1)
    r = gql(M_REDEPLOY, {"serviceId": target["id"], "environmentId": ENV_ID})
    print(r)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "postgres")
