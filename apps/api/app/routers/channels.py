import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.channels import generate_link_code
from app.database import get_db
from app.dependencies import get_owned_business
from app.models import Business, ChannelIdentity
from app.schemas.channels import ChannelIdentitySummary, LinkCodeResponse
from app.whatsapp import display_number

router = APIRouter(prefix="/api/v1/businesses/{business_id}/channels", tags=["channels"])

# v0.6 slice 1: the web-side half of phone<->business linking (see
# app/channels.py's redeem_link_code for the WhatsApp-side half). No
# WHATSAPP_* credentials required to exercise this router -- it only
# reads WHATSAPP_DISPLAY_NUMBER to tell the owner what number to text, and
# is None (omitted from the response) when unset, same "unconfigured is a
# valid state" pattern as app/whatsapp.py.


def _mask(external_id: str) -> str:
    """"+15551234567" -> "•••4567" -- enough for the owner to recognize
    which number a link belongs to without displaying the full number back
    to whoever's looking at their screen."""
    return f"•••{external_id[-4:]}" if len(external_id) > 4 else external_id


@router.post("/whatsapp/link-code", response_model=LinkCodeResponse, status_code=status.HTTP_201_CREATED)
def create_whatsapp_link_code(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    """business.owner_id is used directly as the link code's user_id --
    get_owned_business already proved the current user IS that owner, so
    this carries no less certainty than looking current_user back up
    separately would."""
    link_code = generate_link_code(db, business.owner_id, business.id)
    db.commit()
    return LinkCodeResponse(
        code=link_code.code,
        expires_at=link_code.expires_at,
        whatsapp_number=display_number(),
    )


@router.get("/", response_model=list[ChannelIdentitySummary])
def list_channels(business: Business = Depends(get_owned_business), db: Session = Depends(get_db)):
    identities = db.query(ChannelIdentity).filter(ChannelIdentity.business_id == business.id).all()
    return [
        ChannelIdentitySummary(
            id=i.id,
            channel=i.channel,
            display_name=i.display_name,
            masked_external_id=_mask(i.external_id),
            verified_at=i.verified_at,
        )
        for i in identities
    ]


@router.delete("/{channel_identity_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_channel(
    channel_identity_id: uuid.UUID,
    business: Business = Depends(get_owned_business),
    db: Session = Depends(get_db),
):
    identity = db.get(ChannelIdentity, channel_identity_id)
    if identity is None or identity.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel link not found")
    db.delete(identity)
    db.commit()
