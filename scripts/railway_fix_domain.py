"""Recreate service domain with correct targetPort=8080 (Railway's PORT)."""
import json
import sys

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, ENV_ID  # noqa: E402

Q_DOMAINS = """
query($projectId: String!, $environmentId: String!, $serviceId: String!) {
  domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
    serviceDomains { id domain targetPort }
  }
}
"""

Q_FIND_SERVICE = """
query($id: String!) {
  project(id: $id) { services { edges { node { id name } } } }
}
"""

M_UPDATE = """
mutation($input: ServiceDomainUpdateInput!) {
  serviceDomainUpdate(input: $input)
}
"""

M_CREATE = """
mutation($input: ServiceDomainCreateInput!) {
  serviceDomainCreate(input: $input) { domain }
}
"""

M_DELETE = """
mutation($id: String!) { serviceDomainDelete(id: $id) }
"""


def main():
    state = gql(Q_FIND_SERVICE, {"id": PROJECT_ID})
    sid = next(e["node"]["id"] for e in state["data"]["project"]["services"]["edges"]
               if e["node"]["name"] == "oncount-partners")

    d = gql(Q_DOMAINS, {"projectId": PROJECT_ID, "environmentId": ENV_ID, "serviceId": sid})
    print("Domains:", json.dumps(d, ensure_ascii=False))

    if d.get("data") and d["data"].get("domains"):
        for sd in d["data"]["domains"]["serviceDomains"]:
            dr = gql(M_DELETE, {"id": sd["id"]})
            print(f"Deleted {sd['domain']}:", dr)
        cr = gql(M_CREATE, {"input": {
            "environmentId": ENV_ID,
            "serviceId": sid,
            "targetPort": 8080,
        }})
        print("Recreated:", cr)


if __name__ == "__main__":
    main()
