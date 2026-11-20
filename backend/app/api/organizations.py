"""Команды (организации): список, приглашения, вступление. Порт `app.js` §«P2: organizations».

Список организаций и вступление по инвайту доступны без Pro (как в app.js —
`preHandler: requireOwner`), создание команды и приглашения — только Pro.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import OwnerDep, ProOwnerDep, StoreDep
from app.api.schemas.generated import (
    Organization,
    OrganizationCreate,
    OrganizationInvite,
    OrganizationInviteCreate,
    OrganizationJoin,
    OrganizationMember,
)
from app.domain.errors import NotFoundError

router = APIRouter(tags=["organizations"])


@router.get("/api/organizations", response_model=list[Organization])
def list_organizations(owner: OwnerDep, store: StoreDep) -> list[dict]:
    return store.list_organizations_for_owner(owner["id"])


@router.post(
    "/api/organizations", status_code=status.HTTP_201_CREATED, response_model=Organization
)
def create_organization(body: OrganizationCreate, owner: ProOwnerDep, store: StoreDep) -> dict:
    return store.create_organization(owner["id"], body.name)


@router.get("/api/organizations/{org_id}/members", response_model=list[OrganizationMember])
def list_members(org_id: int, owner: ProOwnerDep, store: StoreDep) -> list[dict]:
    org = store.find_organization(org_id)
    if org is None or not store.is_org_member(org["id"], owner["id"]):
        raise NotFoundError("Организация не найдена")
    return store.list_organization_members(org["id"])


@router.post("/api/organizations/{org_id}/invites", response_model=OrganizationInvite)
def create_invite(
    org_id: int, body: OrganizationInviteCreate, owner: ProOwnerDep, store: StoreDep
) -> dict:
    org = store.find_organization(org_id)
    if org is None or org["ownerId"] != owner["id"]:
        raise NotFoundError("Организация не найдена")
    return store.create_organization_invite(org["id"], body.email)


@router.post("/api/organizations/join", response_model=Organization)
def join_organization(body: OrganizationJoin, owner: OwnerDep, store: StoreDep) -> dict:
    return store.join_organization(owner, body.token)
