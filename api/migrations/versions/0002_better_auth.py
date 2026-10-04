"""Better Auth tables (user, session, account, verification, jwks).

Owned and used by the web app's Better Auth instance; created here so one migration system builds the
whole database. Generated with `@better-auth/cli generate` for better-auth 1.7 (email/password + JWT).

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS "user" ("id" text not null primary key, "name" text not null, "email" text not null unique, "emailVerified" boolean not null, "image" text, "createdAt" timestamptz default CURRENT_TIMESTAMP not null, "updatedAt" timestamptz default CURRENT_TIMESTAMP not null)""")
    op.execute("""CREATE TABLE IF NOT EXISTS "session" ("id" text not null primary key, "expiresAt" timestamptz not null, "token" text not null unique, "createdAt" timestamptz default CURRENT_TIMESTAMP not null, "updatedAt" timestamptz not null, "ipAddress" text, "userAgent" text, "userId" text not null references "user" ("id") on delete cascade)""")
    op.execute("""CREATE TABLE IF NOT EXISTS "account" ("id" text not null primary key, "accountId" text not null, "providerId" text not null, "userId" text not null references "user" ("id") on delete cascade, "accessToken" text, "refreshToken" text, "idToken" text, "accessTokenExpiresAt" timestamptz, "refreshTokenExpiresAt" timestamptz, "scope" text, "password" text, "createdAt" timestamptz default CURRENT_TIMESTAMP not null, "updatedAt" timestamptz not null)""")
    op.execute("""CREATE TABLE IF NOT EXISTS "verification" ("id" text not null primary key, "identifier" text not null, "value" text not null, "expiresAt" timestamptz not null, "createdAt" timestamptz default CURRENT_TIMESTAMP not null, "updatedAt" timestamptz default CURRENT_TIMESTAMP not null)""")
    op.execute("""CREATE TABLE IF NOT EXISTS "jwks" ("id" text not null primary key, "publicKey" text not null, "privateKey" text not null, "createdAt" timestamptz not null, "expiresAt" timestamptz, "alg" text, "crv" text)""")
    op.execute("""CREATE INDEX IF NOT EXISTS "session_userId_idx" on "session" ("userId")""")
    op.execute("""CREATE INDEX IF NOT EXISTS "account_userId_idx" on "account" ("userId")""")
    op.execute("""CREATE INDEX IF NOT EXISTS "verification_identifier_idx" on "verification" ("identifier")""")


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "jwks", "verification", "account", "session", "user" CASCADE')
