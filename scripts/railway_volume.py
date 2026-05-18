"""Create persistent volume for postgres service."""
import sys

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, ENV_ID, Q_SERVICES_DETAIL  # noqa: E402

M_VOLUME_CREATE = """
mutation($input: VolumeCreateInput!) {
  volumeCreate(input: $input) { id name }
}
"""


def main():
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    pg = next(e["node"] for e in state["data"]["project"]["services"]["edges"]
              if e["node"]["name"] == "postgres")
    r = gql(M_VOLUME_CREATE, {"input": {
        "projectId": PROJECT_ID,
        "environmentId": ENV_ID,
        "serviceId": pg["id"],
        "mountPath": "/var/lib/postgresql/data",
    }})
    print(r)


if __name__ == "__main__":
    main()
