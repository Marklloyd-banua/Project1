from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member, require_store_owner_or_manager
from app.models.store import Store, StoreMembership
from app.models.storefront import StorefrontSettings
from app.schemas.store import StoreProfileResponse, StoreProfileUpdateRequest
from app.schemas.storefront import StorefrontSettingsResponse

router = APIRouter(prefix="/stores", tags=["stores"])

_STORE_PROFILE_FIELDS = {
    "name",
    "description",
    "logo_image_url",
    "banner_image_url",
    "contact_email",
    "phone_number",
    "business_address",
    "timezone",
    "date_format",
}


@router.get("/{store_id}", response_model=StoreProfileResponse)
def get_store_profile(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> StoreProfileResponse:
    store = db.get(Store, store_id)
    if store is None or membership.store_id != store_id:
        # Membership dependency enforces store access; missing store in authorized context is unexpected.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")
    return StoreProfileResponse.model_validate(store, from_attributes=True)


@router.patch("/{store_id}", response_model=StoreProfileResponse)
def update_store_profile(
    store_id: uuid.UUID,
    payload: StoreProfileUpdateRequest,
    membership: StoreMembership = Depends(require_store_owner_or_manager),
    db: Session = Depends(get_db),
) -> StoreProfileResponse:
    store = db.get(Store, store_id)
    if store is None or membership.store_id != store_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field in _STORE_PROFILE_FIELDS:
            setattr(store, field, value)

    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreProfileResponse.model_validate(store, from_attributes=True)


@router.get("/{store_id}/storefront-settings", response_model=StorefrontSettingsResponse)
def get_storefront_settings(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> StorefrontSettingsResponse:
    settings = db.execute(
        select(StorefrontSettings).where(StorefrontSettings.store_id == store_id)
    ).scalar_one_or_none()
    if settings is None or membership.store_id != store_id:
        # Within authorized store scope, missing settings row must return 404 and never be auto-created.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")
    return StorefrontSettingsResponse.model_validate(settings, from_attributes=True)
