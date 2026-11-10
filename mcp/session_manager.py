import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import socket
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Any

import docker
import httpx
from docker.errors import DockerException, NotFound
from mcp.server.mcpserver.exceptions import ToolError


logger = logging.getLogger(__name__)


class ResourceCreationError(RuntimeError):
    def __init__(self, message: str, burp_id: str, relay_id: str, network_id: str) -> None:
        super().__init__(message)
        self.burp_id = burp_id
        self.relay_id = relay_id
        self.network_id = network_id


@dataclass
class BurpSession:
    session_id: str
    token_hash: bytes
    state: str = "starting"
    error: str | None = None
    expires_at: float | None = None
    active_calls: int = 0
    burp_id: str | None = None
    relay_id: str | None = None
    network_id: str | None = None
    reburp_url: str | None = None
    launch_task: asyncio.Task[None] | None = None
    cleanup_task: asyncio.Task[None] | None = None


class SessionManager:
    def __init__(self) -> None:
        self.client: docker.DockerClient | None = None
        self.manager_id = ""
        self.project = ""
        self.burp_image = os.environ.get("BURP_IMAGE", "")
        self.mcp_image = os.environ.get("MCP_IMAGE", "")
        try:
            self.idle_seconds = int(os.environ.get("BURP_IDLE_SECONDS", "300"))
            self.max_sessions = int(os.environ.get("MAX_BURP_SESSIONS", "2"))
        except ValueError as exc:
            raise RuntimeError("BURP_IDLE_SECONDS and MAX_BURP_SESSIONS must be integers") from exc
        if self.idle_seconds < 1 or self.max_sessions < 1:
            raise RuntimeError("BURP_IDLE_SECONDS and MAX_BURP_SESSIONS must be positive")
        self.sessions: dict[str, BurpSession] = {}
        self.lock = asyncio.Lock()
        self.reaper_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        if not self.burp_image or not self.mcp_image:
            raise RuntimeError("BURP_IMAGE and MCP_IMAGE must be set")
        if os.environ.get("BURP_ACCEPT_EULA") != "true":
            raise RuntimeError("Set BURP_ACCEPT_EULA=true after accepting the Burp license agreement")
        try:
            self.client = docker.from_env()
            await asyncio.to_thread(self.client.ping)
            manager = await asyncio.to_thread(self.client.containers.get, socket.gethostname())
            self.manager_id = manager.id
            self.project = manager.labels.get("com.docker.compose.project", "")
            if not self.project:
                raise RuntimeError("The MCP container must be started by Docker Compose")
            await asyncio.to_thread(self._remove_orphans)
        except DockerException as exc:
            raise RuntimeError(f"Failed to initialize Docker session management: {exc}") from exc
        self.reaper_task = asyncio.create_task(self._reap_expired())

    async def shutdown(self) -> None:
        if self.reaper_task is not None:
            self.reaper_task.cancel()
            try:
                await self.reaper_task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            sessions = list(self.sessions.values())
            for session in sessions:
                session.state = "stopping"
        await asyncio.gather(
            *(session.launch_task for session in sessions if session.launch_task is not None)
        )
        while any(session.active_calls for session in sessions):
            await asyncio.sleep(0.1)
        await asyncio.gather(
            *(session.cleanup_task for session in sessions if session.cleanup_task is not None)
        )
        await asyncio.gather(
            *(self._cleanup(session) for session in sessions if session.session_id in self.sessions)
        )
        if self.client is not None:
            self.client.close()

    async def start(self) -> dict[str, str]:
        async with self.lock:
            allocated = sum(session.state != "failed" for session in self.sessions.values())
            if allocated >= self.max_sessions:
                raise ToolError(f"Burp session limit reached ({self.max_sessions})")
            session_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            session = BurpSession(session_id, hashlib.sha256(token.encode()).digest())
            self.sessions[session_id] = session
            session.launch_task = asyncio.create_task(self._launch(session))
        return {"session_id": session_id, "session_token": token, "state": "starting"}

    async def status(self, session_id: str, session_token: str) -> dict[str, Any]:
        async with self.lock:
            session = self._authorize(session_id, session_token)
            self._expire_if_needed(session)
            if session.state == "ready":
                session.expires_at = max(session.expires_at or 0, time.monotonic() + self.idle_seconds)
            return self._describe(session)

    async def extend(self, session_id: str, session_token: str, seconds: int) -> dict[str, Any]:
        if not 1 <= seconds <= 3600:
            raise ToolError("seconds must be between 1 and 3600")
        async with self.lock:
            session = self._authorize(session_id, session_token)
            self._expire_if_needed(session)
            if session.state != "ready" or session.expires_at is None:
                raise ToolError(f"Burp session {session_id} is {session.state}, not ready")
            session.expires_at = max(session.expires_at, time.monotonic()) + seconds
            return self._describe(session)

    async def stop(self, session_id: str, session_token: str) -> dict[str, str]:
        async with self.lock:
            session = self._authorize(session_id, session_token)
            if session.state not in {"stopping", "failed"}:
                session.state = "stopping"
            launch_done = session.launch_task is None or session.launch_task.done()
            if launch_done and session.active_calls == 0 and session.cleanup_task is None:
                session.cleanup_task = asyncio.create_task(self._cleanup(session))
        return {"session_id": session_id, "state": session.state}

    @asynccontextmanager
    async def use(self, session_id: str, session_token: str) -> AsyncIterator[str]:
        async with self.lock:
            session = self._authorize(session_id, session_token)
            self._expire_if_needed(session)
            if session.state != "ready" or session.reburp_url is None:
                raise ToolError(f"Burp session {session_id} is {session.state}, not ready")
            session.active_calls += 1
            session.expires_at = max(session.expires_at or 0, time.monotonic() + self.idle_seconds)
            reburp_url = session.reburp_url
        try:
            yield reburp_url
        finally:
            async with self.lock:
                session.active_calls -= 1
                if session.state == "ready":
                    session.expires_at = max(session.expires_at or 0, time.monotonic() + self.idle_seconds)
                elif session.state == "stopping" and session.active_calls == 0:
                    if session.cleanup_task is None:
                        session.cleanup_task = asyncio.create_task(self._cleanup(session))

    def _authorize(self, session_id: str, session_token: str) -> BurpSession:
        session = self.sessions.get(session_id)
        supplied_hash = hashlib.sha256(session_token.encode()).digest()
        if session is None or not hmac.compare_digest(session.token_hash, supplied_hash):
            raise ToolError(f"Unknown or unauthorized Burp session: {session_id}")
        return session

    def _expire_if_needed(self, session: BurpSession) -> None:
        if session.state == "ready" and session.active_calls == 0:
            if session.expires_at is not None and session.expires_at <= time.monotonic():
                session.state = "stopping"
                if session.cleanup_task is None:
                    session.cleanup_task = asyncio.create_task(self._cleanup(session))

    def _describe(self, session: BurpSession) -> dict[str, Any]:
        result: dict[str, Any] = {"session_id": session.session_id, "state": session.state}
        if session.expires_at is not None and session.state == "ready":
            result["idle_seconds_remaining"] = max(0, int(session.expires_at - time.monotonic()))
        if session.error is not None:
            result["error"] = session.error
        return result

    async def _launch(self, session: BurpSession) -> None:
        try:
            burp_id, relay_id, network_id, reburp_url = await asyncio.to_thread(
                self._create_resources, session.session_id
            )
            async with self.lock:
                session.burp_id = burp_id
                session.relay_id = relay_id
                session.network_id = network_id
                session.reburp_url = reburp_url
                stopping = session.state == "stopping"
            if stopping:
                await self._cleanup(session)
                return
            await self._wait_ready(session)
            async with self.lock:
                if session.state == "starting":
                    session.state = "ready"
                    session.expires_at = time.monotonic() + self.idle_seconds
                else:
                    session.cleanup_task = asyncio.create_task(self._cleanup(session))
        except Exception as exc:
            if isinstance(exc, ResourceCreationError):
                session.burp_id = exc.burp_id or None
                session.relay_id = exc.relay_id or None
                session.network_id = exc.network_id or None
            async with self.lock:
                session.state = "failed"
                session.error = f"Failed to start Burp session {session.session_id}: {exc}"
                session.expires_at = time.monotonic() + self.idle_seconds
                logger.error(session.error)
            if session.network_id is not None:
                try:
                    await asyncio.to_thread(self._remove_resources, session)
                except Exception as cleanup_exc:
                    async with self.lock:
                        session.state = "cleanup_failed"
                        session.error += f"; cleanup failed: {cleanup_exc}"
                        logger.error(session.error)

    async def _wait_ready(self, session: BurpSession) -> None:
        if session.reburp_url is None:
            raise RuntimeError("Reburp URL is missing")
        deadline = time.monotonic() + 360
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            while time.monotonic() < deadline:
                async with self.lock:
                    if session.state == "stopping":
                        return
                try:
                    response = await client.get(f"{session.reburp_url}/api/status")
                    response.raise_for_status()
                    return
                except httpx.HTTPError as exc:
                    last_error = exc
                if session.burp_id is not None:
                    state = await asyncio.to_thread(self._container_state, session.burp_id)
                    if state != "running":
                        raise RuntimeError(f"Burp container {session.burp_id} exited ({state})")
                await asyncio.sleep(2)
        raise RuntimeError(
            f"Reburp did not become ready within 360 seconds for {session.session_id}: {last_error}"
        )

    def _container_state(self, container_id: str) -> str:
        assert self.client is not None
        container = self.client.containers.get(container_id)
        return container.status

    def _create_resources(self, session_id: str) -> tuple[str, str, str, str]:
        assert self.client is not None
        project_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", self.project)
        name = f"{project_name}-blurp-{session_id}"
        labels = {
            "io.blurp.managed": "true",
            "io.blurp.project": self.project,
            "io.blurp.session": session_id,
        }
        burp_id = relay_id = network_id = ""
        try:
            network = self.client.networks.create(name, driver="bridge", labels=labels)
            network_id = network.id
            network.connect(self.manager_id)
            burp = self.client.containers.run(
                self.burp_image,
                detach=True,
                name=name,
                network=network.name,
                environment={"BURP_ACCEPT_EULA": "true"},
                labels={**labels, "io.blurp.role": "burp"},
                init=True,
            )
            burp_id = burp.id
            relay = self.client.containers.run(
                self.mcp_image,
                command=["python", "relay.py"],
                detach=True,
                name=f"{name}-relay",
                network_mode=f"container:{burp_id}",
                labels={**labels, "io.blurp.role": "relay"},
                init=True,
            )
            relay_id = relay.id
            burp.reload()
            ip_address = burp.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]
            if not ip_address:
                raise RuntimeError(f"Burp container {burp_id} has no address on {network.name}")
            return burp_id, relay_id, network_id, f"http://{ip_address}:9091"
        except Exception as exc:
            partial = BurpSession(
                session_id,
                b"",
                burp_id=burp_id or None,
                relay_id=relay_id or None,
                network_id=network_id or None,
            )
            try:
                self._remove_resources(partial)
            except Exception as cleanup_exc:
                raise ResourceCreationError(
                    f"Creation failed: {exc}; cleanup failed: {cleanup_exc}",
                    burp_id,
                    relay_id,
                    network_id,
                ) from exc
            raise RuntimeError(f"Creation failed: {exc}") from exc

    def _remove_orphans(self) -> None:
        assert self.client is not None
        filters = {"label": ["io.blurp.managed=true", f"io.blurp.project={self.project}"]}
        containers = self.client.containers.list(all=True, filters=filters)
        containers.sort(key=lambda item: item.labels.get("io.blurp.role") != "relay")
        errors = []
        for container in containers:
            try:
                container.remove(force=True)
            except NotFound:
                pass
            except DockerException as exc:
                errors.append(f"remove container {container.id}: {exc}")
        for network in self.client.networks.list(filters=filters):
            try:
                self._remove_network(network.id)
            except DockerException as exc:
                errors.append(f"remove network {network.id}: {exc}")
        if errors:
            raise RuntimeError("Failed to remove previous Burp sessions: " + "; ".join(errors))

    def _remove_network(self, network_id: str) -> None:
        assert self.client is not None
        try:
            network = self.client.networks.get(network_id)
        except NotFound:
            return
        if self.manager_id in network.attrs.get("Containers", {}):
            network.disconnect(self.manager_id, force=True)
        network.remove()

    def _remove_resources(self, session: BurpSession) -> None:
        assert self.client is not None
        errors = []
        for container_id in (session.relay_id, session.burp_id):
            if container_id is None:
                continue
            try:
                self.client.containers.get(container_id).remove(force=True)
            except NotFound:
                pass
            except DockerException as exc:
                errors.append(f"remove container {container_id}: {exc}")
        if session.network_id is not None:
            try:
                self._remove_network(session.network_id)
            except DockerException as exc:
                errors.append(f"remove network {session.network_id}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    async def _cleanup(self, session: BurpSession) -> None:
        try:
            await asyncio.to_thread(self._remove_resources, session)
        except Exception as exc:
            async with self.lock:
                session.state = "cleanup_failed"
                session.error = f"Failed to remove Burp session {session.session_id}: {exc}"
                session.cleanup_task = None
                logger.error(session.error)
        else:
            async with self.lock:
                self.sessions.pop(session.session_id, None)

    async def _reap_expired(self) -> None:
        while True:
            await asyncio.sleep(5)
            async with self.lock:
                now = time.monotonic()
                for session in list(self.sessions.values()):
                    if session.state == "failed" and session.expires_at is not None:
                        if session.expires_at <= now:
                            self.sessions.pop(session.session_id, None)
                        continue
                    if session.state == "ready" and session.expires_at is not None:
                        if session.expires_at <= now and session.active_calls == 0:
                            session.state = "stopping"
                    if session.state in {"stopping", "cleanup_failed"}:
                        launch_done = session.launch_task is None or session.launch_task.done()
                        if launch_done and session.active_calls == 0 and session.cleanup_task is None:
                            session.cleanup_task = asyncio.create_task(self._cleanup(session))
