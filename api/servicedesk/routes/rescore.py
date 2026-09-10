"""Manual rescore (spec D.5). Manager-only, and it assigns nobody.

A rescore refreshes stored risk estimates after a policy edit or a change in
availability. It is the manager's tool, so it is guarded by
``deps.current_manager`` rather than by a check inside the service, and it never
touches ``current_assignee_id``: a ticket a dispatcher already accepted stays
where a human put it, whatever the new score says (spec B.2).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db.session import get_db
from api.servicedesk.domain import schemas
from api.servicedesk.services import decisions as decision_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("/rescore", response_model=schemas.RescoreResponse)
def rescore_tickets(
    payload: schemas.RescoreRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    summary = decision_service.rescore(
        db,
        actor,
        only_stale=payload.only_stale,
        stale_after_minutes=payload.stale_after_minutes,
        as_of=payload.as_of,
    )
    return schemas.RescoreResponse(
        considered=summary["considered"],
        rescored=summary["rescored"],
        unchanged=summary["unchanged"],
        request_id=request_id,
    )
