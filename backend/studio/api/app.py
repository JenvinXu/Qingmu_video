from __future__ import annotations
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from ..core.paths import TOKEN, INTERNAL_TOKEN, DATA, media_path, new_media_path
from ..core.store import store, Conflict
from ..core.network import async_client
from ..domain import projects
from ..domain.models import (
    AssetMeta,
    CharacterCreate,
    ChatRequest,
    CollectRequest,
    CreateProject,
    ProjectPatch,
    PromptPatch,
    RunRequest,
    Settings,
)
from ..jobs.manager import jobs
from ..library import service as library
from ..library import sources as media_sources
from ..library.characters import create_character, voice_metadata
from ..media.process import executable
from ..providers.settings import (
    read_settings,
    save_settings,
    safe_error,
    llm_connection,
)
from ..providers.llm import LLM
from ..providers.agnes import Agnes
from ..providers.responses import normalize_input, ResponseObserver
from ..providers.voice import VOICES
from ..providers.capabilities import video_capabilities
from ..agent.client import agent_run, cancel_agent, gateway_url
from ..agent.tools import execute
from ..agent import prompts
from ..workflows import production
from ..workflows.acceptance import acceptance


@asynccontextmanager
async def lifespan(app):
    jobs.recover()
    yield
    for task in list(jobs.tasks.values()):
        task.cancel()
    await asyncio.gather(*list(jobs.tasks.values()), return_exceptions=True)


app = FastAPI(title="青幕视频内核", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5178", "null"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def authorization(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if request.url.path.startswith("/api/media/"):
        supplied = supplied or request.query_params.get("token", "")
    import secrets

    expected = (
        INTERNAL_TOKEN if request.url.path.startswith("/api/internal/") else TOKEN
    )
    if not secrets.compare_digest(supplied, expected):
        return JSONResponse(
            {"detail": "本地会话已失效，请重新打开软件"}, status_code=401
        )
    try:
        return await call_next(request)
    except Conflict as error:
        return JSONResponse({"detail": str(error)}, status_code=409)
    except KeyError:
        return JSONResponse({"detail": "项目、任务或素材不存在"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"detail": safe_error(error)}, status_code=422)
    except Exception as error:
        return JSONResponse({"detail": safe_error(error)}, status_code=500)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "service": "lime-studio"}


@app.get("/api/diagnostics")
async def diagnostics():
    media = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            media[name] = {"ready": True, "path": executable(name)}
        except Exception as exc:
            media[name] = {"ready": False, "error": str(exc)}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            result = await client.get(
                gateway_url() + "/health",
                headers={"Authorization": "Bearer " + INTERNAL_TOKEN},
            )
            agent = result.json()
    except Exception:
        agent = {"ready": False, "error": "Codex 服务未连接"}
    return {
        "media": media,
        "agent": agent,
        "database": {"ready": True, "path": str(DATA / "studio.sqlite3")},
        "data_dir": str(DATA),
        "key_configured": read_settings()["key_configured"],
        "video_key_configured": read_settings()["video_key_configured"],
        "llm_key_configured": read_settings()["llm_key_configured"],
    }


@app.get("/api/settings")
async def settings():
    return read_settings()


@app.get("/api/prompts")
async def prompt_library():
    return prompts.catalog()


@app.put("/api/prompts/{ident}")
async def update_prompt(ident: str, value: PromptPatch):
    return prompts.update(ident, value.text, value.revision)


@app.put("/api/settings")
async def update_settings(value: Settings):
    if any(j["status"] in {"queued", "running"} for j in store.list("job")):
        raise ValueError("制作期间不能切换模型，请等待任务完成")
    return save_settings(value)


@app.post("/api/settings/test")
async def test_settings(service: str = "text"):
    if service == "video":
        return await Agnes().test_video()
    return await LLM().test()


@app.get("/api/settings/models")
async def available_models(service: str = "media"):
    result = await (
        LLM().request("GET", "/models")
        if service == "llm"
        else Agnes().request(
            "GET", "/models", credential="video" if service == "video" else "media"
        )
    )
    return [item["id"] for item in result.get("data", []) if item.get("id")]


@app.get("/api/voices")
async def voices():
    return VOICES


@app.get("/api/settings/video-capabilities")
async def model_video_capabilities(model: str):
    return video_capabilities(model)


@app.get("/api/projects")
async def list_projects():
    return [projects.get(project["id"]) for project in store.list("project")]


@app.post("/api/projects")
async def create_project(value: CreateProject):
    return projects.create(value)


@app.get("/api/projects/{ident}")
async def get_project(ident: str):
    return projects.get(ident)


async def _auto_produce(ident: str, job_id: str):
    """Keep long rendering in the backend job instead of a timed App Server tool."""
    current = projects.get(ident)
    planning = None
    if not current.get("scenes"):
        planning = await agent_run(ident, job_id, "", "plan")
    produced = await production.produce(ident, job_id)
    return {"planning": planning, "production": produced}


@app.patch("/api/projects/{ident}")
async def update_project(ident: str, value: ProjectPatch):
    if jobs.busy(ident):
        raise ValueError("当前作品正在制作，请等待完成或取消任务后再修改")
    return projects.patch(ident, value)


@app.delete("/api/projects/{ident}")
async def delete_project(ident: str):
    if jobs.busy(ident):
        raise ValueError("制作中的作品不能移除")
    projects.get(ident)
    store.delete("project", ident)
    return {"removed": True}


@app.post("/api/projects/{ident}/run")
async def run_project(ident: str, value: RunRequest):
    project = projects.get(ident)
    if value.action == "idea" and not project["prompt"].strip():
        raise ValueError("请先输入你的想法")
    if value.action == "storyboard" and not project.get("script", "").strip():
        raise ValueError("请先输入视频文案")
    if (
        value.action in {"plan", "auto"}
        and not project["prompt"].strip()
        and not project["scenes"]
    ):
        raise ValueError("请写一段创作要求")

    async def operation(job_id):
        if value.action == "auto":
            return await _auto_produce(ident, job_id)
        if value.action in {"idea", "storyboard", "plan"}:
            return await agent_run(ident, job_id, "", value.action)
        if value.action == "export":
            return await production.export(ident, job_id)
        if value.action == "materials":
            return await production.collect_materials(ident, job_id)
        if value.action in {"images", "videos", "voices"}:
            return await production.generate_stage(ident, job_id, value.action)
        ids = (
            [value.scene_id] if value.scene_id else [s["id"] for s in project["scenes"]]
        )
        results = []
        for scene_id in ids:
            results.append(
                await production.generate_scene(ident, scene_id, value.action, job_id)
            )
        return results

    return jobs.start(value.action, ident, operation)


@app.post("/api/projects/{ident}/chat")
async def chat(ident: str, value: ChatRequest):
    projects.get(ident)
    return jobs.start(
        "chat", ident, lambda job_id: agent_run(ident, job_id, value.message)
    )


@app.get("/api/jobs")
async def list_jobs():
    return store.list("job")


@app.get("/api/jobs/{ident}")
async def get_job(ident: str):
    return store.get("job", ident)


@app.post("/api/jobs/{ident}/cancel")
async def cancel_job(ident: str):
    await cancel_agent(ident)
    return await jobs.cancel(ident)


@app.get("/api/assets")
async def assets():
    return store.list("asset", 1000)


@app.post("/api/assets/import")
async def import_asset(
    file: UploadFile = File(...),
    kind: str = Form("image"),
    description: str = Form(""),
    voice: str = Form(""),
):
    meta = AssetMeta(
        kind=kind, name=file.filename or "素材", description=description, voice=voice
    )
    suffix = Path(meta.name).suffix.lower()
    allowed = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".mp4",
        ".webm",
        ".mov",
        ".mp3",
        ".wav",
        ".ogg",
        ".txt",
        ".md",
    }
    if suffix not in allowed:
        raise ValueError("请选择 PNG、JPG、WebP、MP4、WebM、音频、TXT 或 Markdown 文件")
    relative, path = new_media_path(suffix)
    try:
        size = 0
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > library.MAX_BYTES:
                    raise ValueError("素材超过 256 MB")
                target.write(chunk)
        return await library.register(
            relative,
            meta.name,
            meta.kind,
            description=meta.description,
            voice=meta.voice,
            source="local",
            license="用户导入",
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.patch("/api/assets/{ident}")
async def edit_asset(ident: str, value: AssetMeta):
    if any(j["status"] in {"running", "queued"} for j in store.list("job")):
        raise ValueError("制作期间不能修改素材，请等待任务完成")
    original = library.asset(ident)
    groups = (
        {"character", "prop", "image"},
        {"voice", "music"},
        {"video"},
        {"document"},
    )
    if not any(original["kind"] in group and value.kind in group for group in groups):
        raise ValueError("只能在相同媒体类型内调整分类")
    voice_metadata(value.voice_asset_id)
    original.update(value.model_dump(exclude_unset=True))
    return store.save("asset", original)


@app.delete("/api/assets/{ident}")
async def remove_asset(ident: str):
    library.asset(ident)
    if any(a.get("voice_asset_id") == ident for a in store.list("asset", 1000)):
        raise ValueError("该声音正在被角色使用，请先修改角色声音")
    for project in store.list("project", 1000):
        if (
            project.get("bgm_id") == ident
            or project.get("export_id") == ident
            or ident in project.get("asset_ids", [])
            or any(
                ident in s.get("asset_ids", [])
                or ident in s.get("reference_ids", [])
                or ident
                in [
                    s.get("first_frame_id"),
                    s.get("video_id"),
                    s.get("audio_id"),
                    s.get("sfx_id"),
                ]
                for s in project["scenes"]
            )
        ):
            raise ValueError("素材正在被作品使用，请先解除绑定")
    store.delete("asset", ident)
    return {"removed": True}


@app.post("/api/library/collect")
async def collect(value: CollectRequest):
    metadata = value.model_dump(exclude={"url", "name", "license"})
    return await library.collect(value.url, value.name, value.license, **metadata)


@app.get("/api/library/search")
async def search(query: str, media_type: str = "all", providers: str = ""):
    if len(query) < 2 or len(query) > 120:
        raise ValueError("搜索词长度为 2–120 个字符")
    if media_type not in {"all", "video", "image", "audio"}:
        raise ValueError("素材类型应为 video、image、audio 或 all")
    selected = {value.strip() for value in providers.split(",") if value.strip()}
    tasks = []
    if media_type in {"all", "video"}:
        tasks.append(media_sources.search_videos(query, selected or None))
    if media_type in {"all", "image"}:
        tasks.append(library.search_openverse(query))
        tasks.append(library.search_commons(query))
    if media_type == "audio":
        tasks.append(library.search_openverse_audio(query))
    values = []
    for result in await asyncio.gather(*tasks):
        values.extend(result)
    for value in values:
        value.setdefault("provider", "openverse")
        value.setdefault("kind", "image")
        if "score" not in value:
            media_sources.rank_candidate(query, value)
    return sorted(
        values,
        key=lambda item: (
            0 if item.get("kind") == "video" else 1,
            -int(item.get("score") or 0),
        ),
    )[:40]


@app.get("/api/library/sources")
async def sources():
    return [
        {
            "id": "local",
            "name": "本地素材",
            "description": "图片、视频、音频和文稿导入",
            "ready": True,
        },
        {
            "id": "openverse",
            "name": "Openverse",
            "description": "搜索开放许可图片与音频，保存作者、来源与许可",
            "ready": True,
            "url": "https://openverse.org",
        },
        *media_sources.source_status(),
        {
            "id": "url",
            "name": "公开链接",
            "description": "下载素材，也可用作模型参考",
            "ready": True,
        },
        {
            "id": "agnes",
            "name": "Agnes 模型生成",
            "description": "生成首帧与分镜视频，保存模型与任务 ID",
            "ready": read_settings()["key_configured"],
        },
    ]


@app.get("/api/media/{relative}")
async def media(relative: str, download: bool = False):
    path = media_path(relative)
    if not path.is_file():
        raise HTTPException(404, "媒体文件不存在")
    return FileResponse(path, filename=path.name if download else None)


@app.get("/api/traces")
async def traces():
    return store.list("trace", 200)


@app.get("/api/reports")
async def reports():
    return store.list("report")


@app.post("/api/acceptance")
async def accept(resume: bool = True):
    if any(j["status"] in {"queued", "running"} for j in store.list("job")):
        raise ValueError("请先等待当前任务完成")
    return jobs.start("acceptance", None, lambda ident: acceptance(ident, resume))


@app.get("/api/internal/agent-config")
async def agent_config():
    return llm_connection()


@app.post("/api/internal/tools")
async def internal_tool(request: Request):
    value = await request.json()
    return await execute(
        value["projectId"], value["jobId"], value["name"], value.get("arguments", {})
    )


@app.post("/api/internal/agent-event")
async def agent_event(request: Request):
    value = await request.json()
    job_id = value.pop("jobId", None)
    if job_id and store.get("job", job_id)["status"] != "running":
        return {"ignored": True}
    value["kind"] = "agent"
    value["job_id"] = job_id
    value["time"] = time.time()
    store.save("trace", value)
    return {"saved": True}


@app.post("/api/internal/provider/responses")
async def provider_proxy(request: Request):
    """Forward native Responses streaming through the tested Python HTTP transport."""
    payload = await request.json()
    config = llm_connection()
    payload["input"] = normalize_input(
        payload.get("input"), assistant_output=config["provider"] != "media"
    )
    payload["model"] = config["text_model"]
    payload["store"] = False
    payload["tools"] = [
        t
        for t in payload.get("tools", [])
        if t.get("type") == "function" and t.get("name", "").startswith("studio_")
    ]
    for tool in payload["tools"]:
        tool.pop("defer_loading", None)
    for key in (
        "metadata",
        "prompt_cache_key",
        "include",
        "service_tier",
        "parallel_tool_calls",
    ):
        payload.pop(key, None)
    client = async_client(
        target_url=config["base_url"], timeout=httpx.Timeout(180, connect=20)
    )
    started = time.time()
    upstream = client.build_request(
        "POST",
        config["base_url"] + "/responses",
        json=payload,
        headers={
            "Authorization": "Bearer " + config["api_key"],
            "Accept": "text/event-stream",
        },
    )
    try:
        response = await client.send(upstream, stream=True)
    except BaseException:
        await client.aclose()
        raise
    if response.is_error:
        text = safe_error(
            RuntimeError((await response.aread()).decode("utf-8", errors="replace"))
        )
        await client.aclose()
        store.save(
            "trace",
            {
                "kind": "agent_model",
                "status": "failed",
                "error": text,
                "http_status": response.status_code,
            },
        )
        return JSONResponse(
            {"error": {"message": text}}, status_code=response.status_code
        )

    async def stream():
        size = 0
        status = "completed"
        failure = None
        observer = ResponseObserver()
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                observer.feed(chunk)
                yield chunk
        except asyncio.CancelledError:
            status = observer.status or "cancelled"
            raise
        except Exception as error:
            status = "failed"
            failure = safe_error(error)
            raise
        finally:
            await response.aclose()
            await client.aclose()
            store.save(
                "trace",
                {
                    "kind": "agent_model",
                    "status": observer.status or status,
                    "error": failure
                    or (
                        safe_error(RuntimeError(str(observer.error)))
                        if observer.error
                        else None
                    ),
                    "usage": observer.usage,
                    "request_id": observer.request_id,
                    "model": config["text_model"],
                    "provider": config["provider"],
                    "duration_ms": round((time.time() - started) * 1000),
                    "response_bytes": size,
                    "tool_count": len(payload["tools"]),
                },
            )

    return StreamingResponse(
        stream(), media_type=response.headers.get("content-type", "text/event-stream")
    )


@app.post("/api/assets/{ident}/analyze")
async def analyze_asset(ident: str):
    return await LLM().inspect_asset(ident)


@app.post("/api/characters")
async def add_character(value: CharacterCreate):
    if value.image_prompt.strip():
        voice_metadata(value.voice_asset_id)

        async def operation(job_id):
            character = await production.make_character(value, job_id)
            return {"asset_id": character["id"], "kind": "character"}

        return {"job": jobs.start("character", None, operation)}
    return {"asset": create_character(value)}


@app.post("/api/projects/{ident}/scenes/{scene_id}/previous-tail")
async def extract_previous_tail(ident: str, scene_id: str):
    if jobs.busy(ident):
        raise ValueError("当前作品正在制作，请等待任务完成")
    return await production.attach_previous_tail(ident, scene_id)


@app.post("/api/assets/generate")
async def generate_asset(request: Request):
    value = await request.json()
    kind = value.get("kind", "image")
    if (
        kind not in {"character", "prop", "image"}
        or not value.get("prompt", "").strip()
    ):
        raise ValueError("请选择图片资产类型并填写描述")
    meta = AssetMeta(
        kind=kind,
        name=value.get("name", "新资产"),
        description=value["prompt"],
        voice=value.get("voice", ""),
    )

    async def operation(job_id):
        jobs.event(job_id, "image", "正在生成创作资产", 15)
        result = await Agnes().image(meta.description, "1:1", [], meta.name)
        result.update(kind=meta.kind, description=meta.description, voice=meta.voice)
        store.save("asset", result)
        return {"asset_id": result["id"], "name": result["name"]}

    return jobs.start("asset", None, operation)
