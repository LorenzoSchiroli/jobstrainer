import uuid as _uuid
import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.types import Command

from backend.database import get_session
from backend.models import User, Job, Company
from backend.tailorer.models import ApplicantProfile, Application
from backend.tailorer.schemas import ProfileUpsert, ProfileResponse
from backend.tailorer.state import TailorerState
from backend.tailorer.agent import build_graph
from backend.auth.dependencies import get_current_user

router = APIRouter(prefix="/tailorer", tags=["tailorer"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


@router.put("/profile", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpsert,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, val)
    await session.commit()
    await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


async def _get_user_from_token(token: str, session: AsyncSession) -> User:
    from backend.auth.jwt import decode_access_token
    # decode_access_token returns the user_id (sub) as a str directly
    user_id = decode_access_token(token)
    if not user_id:
        raise ValueError("Invalid token")
    result = await session.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return user


async def _handle_interrupt(ws: WebSocket, interrupt_val: dict) -> dict:
    """Route one interrupt payload to the extension and return the response."""
    itype = interrupt_val.get("type")

    if itype == "navigate":
        await ws.send_json({"type": "navigate", "url": interrupt_val["url"]})
        return await ws.receive_json()

    elif itype == "request_snapshot":
        await ws.send_json({"type": "request_snapshot"})
        return await ws.receive_json()

    elif itype == "fill_and_confirm":
        for cmd in interrupt_val.get("commands", []):
            await ws.send_json(cmd)
        await ws.send_json({
            "type": "show_confirm",
            "summary": interrupt_val.get("summary", ""),
            "uncertain_fields": interrupt_val.get("uncertain_fields", []),
        })
        return await ws.receive_json()

    elif itype == "show_confirm":
        await ws.send_json(interrupt_val)
        return await ws.receive_json()

    elif itype == "navigate_next":
        await ws.send_json({"type": "navigate_next"})
        return await ws.receive_json()

    elif itype == "show_stuck":
        await ws.send_json({"type": "show_stuck", "message": interrupt_val["message"]})
        return await ws.receive_json()

    return {"type": "unknown"}


@router.websocket("/ws/{job_id}")
async def tailorer_ws(
    websocket: WebSocket,
    job_id: _uuid.UUID,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    job_result = await session.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    company_result = await session.execute(select(Company).where(Company.id == job.company_id))
    company = company_result.scalar_one_or_none()

    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()

    if not profile or not profile.cv_text:
        await websocket.send_json({"type": "error", "message": "No CV on file. Upload your CV first."})
        await websocket.close()
        return

    thread_id = str(_uuid.uuid4())
    await websocket.send_json({"type": "session_started", "thread_id": thread_id})

    initial_state: TailorerState = {
        "job_id": str(job.id),
        "user_id": str(user.id),
        "job_title": job.title,
        "job_description": job.description or "",
        "company_homepage": company.website if company else "",
        "profile": {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "city": profile.city,
            "country": profile.country,
            "work_auth": profile.work_auth,
            "urls": profile.urls or {},
            "extra_qa": profile.extra_qa or {},
        },
        "cv_text": profile.cv_text or "",
        "apply_url": "",
        "current_page": 0,
        "filled_fields": {},
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "pending_correction": None,
        "retry_count": 0,
        "status": "navigating",
    }

    config = {"configurable": {"thread_id": thread_id}}

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer)

    try:
        current_input = initial_state
        while True:
            await graph.ainvoke(current_input, config)

            state_snapshot = await graph.aget_state(config)
            if not state_snapshot.next:
                await websocket.send_json({"type": "done", "message": "Application submitted!"})
                app_record = Application(user_id=user.id, job_id=job_id)
                session.add(app_record)
                await session.commit()
                break

            interrupts = [i for task in state_snapshot.tasks for i in task.interrupts]
            if not interrupts:
                break

            resume_val = await _handle_interrupt(websocket, interrupts[0].value)
            current_input = Command(resume=resume_val)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await websocket.close()


@router.get("/files/{thread_id}/{file_type}")
async def download_tailored_file(
    thread_id: str,
    file_type: str,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    from fastapi.responses import Response
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token")

    if file_type not in ("cv", "cover_letter"):
        raise HTTPException(status_code=400, detail="file_type must be 'cv' or 'cover_letter'")

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph(checkpointer)
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot or not state_snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")

    values = state_snapshot.values
    if values.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    key = "cv_bytes" if file_type == "cv" else "cl_bytes"
    file_bytes = values.get(key, b"")
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not yet generated")

    filename = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
