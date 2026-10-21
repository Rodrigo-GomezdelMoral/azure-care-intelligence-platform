"""Creates the PostgreSQL roles, the schema and the grants; run by the server's Entra administrator.

Bicep cannot create database roles or tables: they are data-plane objects inside the server, made
through a connection the Entra administrator holds, and Azure Resource Manager has no resource for
them. The Entra principal functions live in the maintenance database `postgres`; the tables and
grants in the application one. The API identity only reads; the deployment identity writes rows
and never owns the schema.
"""

import argparse
import os

import psycopg
from azure.identity import DefaultAzureCredential

from src.components.prep import contract

SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
GRANTS = {"id-careapi": "SELECT", "id-carecicd": "SELECT, INSERT, UPDATE, DELETE"}
SCHEMA = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE TABLE IF NOT EXISTS patients (person_id bigint PRIMARY KEY, embedding vector({dimension}),"
    " readmission_30d boolean, care_manager_contacts_12m int, pdc_180d real, has_caregiver boolean, age real)",
    "CREATE INDEX IF NOT EXISTS patients_embedding ON patients USING hnsw (embedding vector_cosine_ops)",
    "CREATE TABLE IF NOT EXISTS call_list (rank int, person_id bigint, score real, expected_value_eur real,"
    " generated_at timestamptz DEFAULT now())",
)


def connect(host: str, database: str, user: str) -> psycopg.Connection[tuple[object, ...]]:
    token = DefaultAzureCredential().get_token(SCOPE).token
    return psycopg.connect(host=host, dbname=database, user=user, password=token, sslmode="require", autocommit=True)


def main(host: str, database: str, admin: str) -> None:
    with connect(host, "postgres", admin) as maintenance:
        existing = {row[0] for row in maintenance.execute("SELECT rolname FROM pg_roles")}
        for identity in (i for i in GRANTS if i not in existing):
            maintenance.execute("SELECT * FROM pgaadauth_create_principal(%s, false, false)", (identity,))
    with connect(host, database, admin) as connection:
        for statement in SCHEMA:
            connection.execute(statement.format(dimension=contract()["features"]))
        for identity, privileges in GRANTS.items():
            connection.execute(f'GRANT CONNECT ON DATABASE "{database}" TO "{identity}"')
            connection.execute(f'GRANT USAGE ON SCHEMA public TO "{identity}"')
            connection.execute(f'GRANT {privileges} ON patients, call_list TO "{identity}"')
        print(f"schema and grants ready on {host}/{database}: {', '.join(GRANTS)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("POSTGRES_HOST"))
    parser.add_argument("--database", default=os.environ.get("POSTGRES_DATABASE", "care"))
    parser.add_argument("--admin", required=True, help="user principal name of the Entra administrator of the server")
    args = parser.parse_args()
    main(args.host, args.database, args.admin)
