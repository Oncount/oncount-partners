"""Trigger a build of a specific commit SHA on Railway."""
import sys

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, ENV_ID, Q_SERVICES_DETAIL  # noqa: E402

# Try several variations of mutation, Railway schema has been evolving
ATTEMPTS = [
    (
        "serviceInstanceDeployV2 with commitSha",
        """mutation($serviceId: String!, $environmentId: String!, $commitSha: String) {
          serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId, commitSha: $commitSha)
        }""",
        lambda sid, sha: {"serviceId": sid, "environmentId": ENV_ID, "commitSha": sha},
    ),
    (
        "deploymentTriggerCreate",
        """mutation($input: DeploymentTriggerCreateInput!) {
          deploymentTriggerCreate(input: $input) { id }
        }""",
        lambda sid, sha: {"input": {
            "projectId": PROJECT_ID,
            "environmentId": ENV_ID,
            "serviceId": sid,
            "branch": "main",
            "commitSha": sha,
        }},
    ),
    (
        "deploymentTrigger",
        """mutation($input: DeploymentTriggerInput!) {
          deploymentTrigger(input: $input)
        }""",
        lambda sid, sha: {"input": {
            "projectId": PROJECT_ID,
            "environmentId": ENV_ID,
            "serviceId": sid,
            "commitSha": sha,
        }},
    ),
]


def main(name: str, sha: str):
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    sid = next(e["node"]["id"] for e in state["data"]["project"]["services"]["edges"]
               if e["node"]["name"] == name)
    for label, mutation, varbuilder in ATTEMPTS:
        r = gql(mutation, varbuilder(sid, sha))
        print(f"--- {label} ---")
        print(r)
        if r.get("data") and not r.get("errors"):
            print(f"SUCCESS via {label}")
            return


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "oncount-partners",
         sys.argv[2] if len(sys.argv) > 2 else "main")
