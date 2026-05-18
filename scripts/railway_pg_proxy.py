"""Create a TCP proxy for the Postgres service so we can connect from the
developer's machine (Railway's `*.railway.internal` is intra-network only)."""
import json
import sys

sys.path.insert(0, ".")
from scripts.railway import gql, PROJECT_ID, ENV_ID, Q_SERVICES_DETAIL  # noqa: E402

M_PROXY = """
mutation($input: TCPProxyCreateInput!) {
  tcpProxyCreate(input: $input) { id domain proxyPort applicationPort }
}
"""


def main():
    state = gql(Q_SERVICES_DETAIL, {"id": PROJECT_ID})
    pg = next(e["node"] for e in state["data"]["project"]["services"]["edges"]
              if e["node"]["name"] == "postgres")
    r = gql(M_PROXY, {"input": {
        "environmentId": ENV_ID,
        "serviceId": pg["id"],
        "applicationPort": 5432,
    }})
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
