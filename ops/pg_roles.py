"""Creates the PostgreSQL roles for the managed identities and enables pgvector; run once by the Entra administrator.

The Entra principal functions live in the maintenance database `postgres`; the grants belong to the application one.

Bicep cannot create database roles: a role is a data-plane object inside the server, created through a
connection the server's Entra administrator holds, and Azure Resource Manager has no resource for it.
"""

import argparse
import os

import psycopg
from azure.identity import DefaultAzureCredential

SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
IDENTITIES = ("id-careaml", "id-careapi")


def connect(host: str, database: str, user: str) -> psycopg.Connection[tuple[object, ...]]:
    token = DefaultAzureCredential().get_token(SCOPE).token
    return psycopg.connect(host=host, dbname=database, user=user, password=token, sslmode="require", autocommit=True)


def main(host: str, database: str, admin: str) -> None:
    with connect(host, "postgres", admin) as maintenance:
        existing = {row[0] for row in maintenance.execute("SELECT rolname FROM pg_roles")}
        for identity in (i for i in IDENTITIES if i not in existing):
            maintenance.execute("SELECT * FROM pgaadauth_create_principal(%s, false, false)", (identity,))
    with connect(host, database, admin) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for identity in IDENTITIES:
            connection.execute(f'GRANT CONNECT ON DATABASE "{database}" TO "{identity}"')
            connection.execute(f'GRANT USAGE ON SCHEMA public TO "{identity}"')
        connection.execute('GRANT CREATE ON SCHEMA public TO "id-careaml"')
        connection.execute(
            'ALTER DEFAULT PRIVILEGES FOR ROLE "id-careaml" IN SCHEMA public GRANT SELECT ON TABLES TO "id-careapi"'
        )
        print(f"roles ready on {host}/{database}: {', '.join(IDENTITIES)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("POSTGRES_HOST"))
    parser.add_argument("--database", default=os.environ.get("POSTGRES_DATABASE", "care"))
    parser.add_argument("--admin", required=True, help="user principal name of the Entra administrator of the server")
    args = parser.parse_args()
    main(args.host, args.database, args.admin)
