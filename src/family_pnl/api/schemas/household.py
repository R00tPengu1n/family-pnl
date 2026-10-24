import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from family_pnl.domain.identity import Role
from family_pnl.services.households import IssuedInvite, Member


class InviteResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"code": "Zq9w2LhC4sQyU1mXo3PdAw", "expires_at": "2026-10-26T09:00:00Z"}]
        }
    )

    code: str
    expires_at: datetime

    @classmethod
    def of(cls, invite: IssuedInvite) -> "InviteResponse":
        return cls(code=invite.code, expires_at=invite.expires_at)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: Role
    joined_at: datetime

    @classmethod
    def of(cls, member: Member) -> "MemberOut":
        return cls(
            user_id=member.user_id,
            email=member.email,
            display_name=member.display_name,
            role=member.role,
            joined_at=member.joined_at,
        )
