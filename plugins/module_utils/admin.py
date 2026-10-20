"""Matrix access without /sync: Synapse admin API plus single client API calls.

/sync pulls the full state of every room the bot is in. The user and room
modules need a handful of facts each, so they ask for exactly those, and a
batch runs its requests side by side, bounded by one semaphore.
"""
import asyncio
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

from aiohttp import ClientConnectionError

from ansible_collections.eraga.matrix.plugins.module_utils.avatar import Image, load_image
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import AnsibleMatrixClient
from ansible_collections.eraga.matrix.plugins.module_utils.errors import AnsibleMatrixError

CLIENT = "/_matrix/client/v3"
MEDIA_V1 = "/_matrix/client/v1/media"
UPLOAD = "/_matrix/media/v3/upload"
ADMIN = "/_synapse/admin"

# Connection failures are retried this many times...
RETRIES = 6
# ...while 429 is waited out as long as the server asks, up to this many
# seconds per request: Synapse rate-limits state events of admins too.
RATE_LIMIT_PATIENCE = 900


class MatrixHttpError(AnsibleMatrixError):
    def __init__(self, method: str, path: str, status: int, body: Any):
        self.status = status
        self.errcode = body.get("errcode") if isinstance(body, dict) else None
        detail = body.get("error") if isinstance(body, dict) else body
        super().__init__(f"{method} {path}: {status} {self.errcode or ''} {detail}".strip())


def _q(value: str) -> str:
    return quote(value, safe="")


def _media_path(mxc: str) -> str:
    server, media_id = mxc[len("mxc://"):].split("/", 1)
    return f"{MEDIA_V1}/download/{_q(server)}/{_q(media_id)}"


def filename_from_disposition(header: Optional[str]) -> Optional[str]:
    """Filename of a Content-Disposition header; RFC 5987 form wins."""
    if not header:
        return None
    star = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", header, re.I)
    if star:
        return unquote(star.group(2).strip(), encoding=star.group(1) or "utf-8")
    plain = re.search(r'filename\s*=\s*("([^"]*)"|[^;]+)', header, re.I)
    if plain:
        return plain.group(2) if plain.group(2) is not None else plain.group(1).strip()
    return None


class MatrixApi:
    def __init__(self, client: AnsibleMatrixClient, check_mode: bool = False, concurrency: int = 8):
        self.client = client
        self.check_mode = check_mode
        self._slots = asyncio.Semaphore(concurrency)
        self._accounts: Dict[str, asyncio.Future] = {}
        self._images: Dict[str, asyncio.Future] = {}
        self._me: Optional[str] = None

    def mxid(self, login: str) -> str:
        return self.client.login_to_id(login)

    async def close(self):
        await self.client.close()

    # -- transport ---------------------------------------------------------

    async def request(self, method: str, path: str, body: Any = None, raw: Optional[bytes] = None,
                      content_type: str = "application/json", missing_ok: bool = False):
        """Returns (body, headers); (None, None) for a 404 when missing_ok."""
        headers = {"Authorization": f"Bearer {self.client.access_token}"}
        data = None
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type
        elif body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"

        loop = asyncio.get_event_loop()
        give_up_at = loop.time() + RATE_LIMIT_PATIENCE
        attempt = 0
        while True:
            try:
                async with self._slots:
                    resp = await self.client.send(method, path, data, headers)
                    status = resp.status
                    resp_headers = resp.headers
                    if method == "HEAD":
                        payload = None
                    elif "json" in resp.headers.get("Content-Type", ""):
                        payload = await resp.json()
                    else:
                        payload = await resp.read()
                    resp.release()
            except (ClientConnectionError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt >= RETRIES:
                    raise AnsibleMatrixError(f"{method} {path}: {type(e).__name__}: {e}")
                await asyncio.sleep(2 ** attempt)
                continue

            if status == 429:
                wait = (payload.get("retry_after_ms") or 2000) / 1000 if isinstance(payload, dict) else 2
                if loop.time() + wait > give_up_at:
                    raise AnsibleMatrixError(
                        f"{method} {path}: rate limited for over {RATE_LIMIT_PATIENCE}s")
                await asyncio.sleep(wait)
                continue
            if status == 404 and missing_ok:
                return None, None
            if status >= 400:
                raise MatrixHttpError(method, path, status, payload)
            return payload, resp_headers

    # -- identity ----------------------------------------------------------

    async def me(self) -> str:
        if self._me is None:
            body, _ = await self.request("GET", f"{CLIENT}/account/whoami")
            self._me = body["user_id"]
        return self._me

    async def account(self, mxid: str) -> Optional[Dict[str, Any]]:
        """Synapse account, or None when the server has no such user.

        One lookup per mxid per run, however many rooms ask for it.
        """
        if mxid not in self._accounts:
            self._accounts[mxid] = asyncio.ensure_future(self._fetch_account(mxid))
        return await self._accounts[mxid]

    async def _fetch_account(self, mxid: str) -> Optional[Dict[str, Any]]:
        body, _ = await self.request("GET", f"{ADMIN}/v2/users/{_q(mxid)}", missing_ok=True)
        return body

    async def is_active_user(self, mxid: str) -> bool:
        acc = await self.account(mxid)
        return acc is not None and not acc.get("deactivated", False)

    async def update_account(self, mxid: str, content: Dict[str, Any]):
        # PUT on this endpoint CREATES a missing user: only for accounts we found.
        if self.check_mode:
            return
        await self.request("PUT", f"{ADMIN}/v2/users/{_q(mxid)}", body=content)

    # -- media -------------------------------------------------------------

    async def image(self, source: str) -> Image:
        if source not in self._images:
            loop = asyncio.get_event_loop()
            self._images[source] = loop.run_in_executor(None, load_image, source)
        return await self._images[source]

    async def media_filename(self, mxc: str) -> Optional[str]:
        """Upload name of a media item, read from headers only (no body)."""
        _, headers = await self.request("HEAD", _media_path(mxc), missing_ok=True)
        if headers is None:
            return None
        return filename_from_disposition(headers.get("Content-Disposition"))

    async def download(self, mxc: str) -> Optional[bytes]:
        body, _ = await self.request("GET", _media_path(mxc), missing_ok=True)
        return body if isinstance(body, (bytes, bytearray)) else None

    async def upload(self, image: Image) -> str:
        if self.check_mode:
            return "mxc://check-mode/" + image.name
        body, _ = await self.request("POST", f"{UPLOAD}?filename={_q(image.name)}",
                                     raw=image.data, content_type=image.mime)
        return body["content_uri"]

    # -- rooms -------------------------------------------------------------

    async def resolve_alias(self, alias: str) -> Optional[str]:
        body, _ = await self.request("GET", f"{CLIENT}/directory/room/{_q(alias)}", missing_ok=True)
        return body["room_id"] if body else None

    async def room_state(self, room_id: str) -> List[Dict[str, Any]]:
        body, _ = await self.request("GET", f"{ADMIN}/v1/rooms/{_q(room_id)}/state")
        return body["state"]

    async def create_room(self, content: Dict[str, Any]) -> Optional[str]:
        if self.check_mode:
            return None
        body, _ = await self.request("POST", f"{CLIENT}/createRoom", body=content)
        return body["room_id"]

    async def join(self, room_id: str):
        if self.check_mode:
            return
        await self.request("POST", f"{CLIENT}/join/{_q(room_id)}", body={})

    async def put_state(self, room_id: str, event_type: str, content: Dict[str, Any], state_key: str = ""):
        if self.check_mode:
            return
        await self.request("PUT", f"{CLIENT}/rooms/{_q(room_id)}/state/{_q(event_type)}/{_q(state_key)}",
                           body=content)

    async def invite(self, room_id: str, mxid: str):
        if self.check_mode:
            return
        await self.request("POST", f"{CLIENT}/rooms/{_q(room_id)}/invite", body={"user_id": mxid})

    async def kick(self, room_id: str, mxid: str):
        if self.check_mode:
            return
        await self.request("POST", f"{CLIENT}/rooms/{_q(room_id)}/kick", body={"user_id": mxid})

    async def directory_visibility(self, room_id: str) -> str:
        body, _ = await self.request("GET", f"{CLIENT}/directory/list/room/{_q(room_id)}")
        return body["visibility"]

    async def set_directory_visibility(self, room_id: str, visibility: str):
        if self.check_mode:
            return
        await self.request("PUT", f"{CLIENT}/directory/list/room/{_q(room_id)}", body={"visibility": visibility})

    async def delete_room(self, room_id: str, block: bool = False, purge: bool = False):
        if self.check_mode:
            return None
        body, _ = await self.request("DELETE", f"{ADMIN}/v1/rooms/{_q(room_id)}",
                                     body={"block": block, "purge": purge})
        return body
