# noinspection PyPackageRequirements
import os
from dataclasses import *
from tempfile import TemporaryDirectory

import aiofiles
import aiofiles.os
from nio import *
from nio.responses import WhoamiResponse
from nio.api import _FilterT

from ansible_collections.eraga.matrix.plugins.module_utils.errors import AnsibleMatrixError, AnsibleMatrixWarning
from ansible_collections.eraga.matrix.plugins.module_utils.utils import url2file, detect_mime_type, \
    if_svg_convert_to_png

ANSIBLE_MATRIX_DEVICE_ID = "ansible-eraga-matrix-module"


@dataclass
class Convertable(object):
    def dict(self) -> dict:
        result = dict()
        self_dict = asdict(self)

        for k in self_dict:
            if isinstance(self_dict[k], Convertable):
                result[k] = self.__getattribute__(k).dict()
            elif isinstance(self_dict[k], list):
                result[k] = list(map(Convertable.__map_dict__, self.__getattribute__(k))
                                 )
            elif self_dict[k] is not None:
                result[k] = self_dict[k]

        return result

    @staticmethod
    def __map_dict__(it):
        if isinstance(it, Convertable):
            return it.dict()

        return it


class _AnsibleMatrixObject(object):
    def __init__(self, domain: str = ""):
        self.domain = domain

    def login_to_id(self, login: Optional[str]) -> Optional[str]:
        if login is None:
            return None

        if login.startswith("@") and ":" in login:
            return login

        return "@{}:{}".format(login, self.domain)

    def room_alias_to_mx_alias(self, alias: str) -> str:
        if alias.startswith("!") and ":" in alias:
            return alias

        if alias.startswith("#") and ":" in alias:
            return alias

        return "#{}:{}".format(alias, self.domain)

    def localpart_to_mx_group(self, localpart: str) -> str:
        if localpart.startswith("+") and ":" in localpart:
            return localpart

        return "+{}:{}".format(localpart, self.domain)


class AnsibleMatrixClient(_AnsibleMatrixObject, AsyncClient):
    """A Matrix client implementation for Ansible modules.

    This class extends both _AnsibleMatrixObject and AsyncClient to provide Matrix
    client functionality specifically tailored for Ansible automation tasks.

    The client handles Matrix protocol operations such as authentication, room management,
    message sending, and file uploads while providing Ansible-specific conveniences
    and error handling.

    Attributes:
        domain (str): The Matrix server domain.
        uri (str): The Matrix homeserver URI.
        token (str): The access token for authentication.
        user (Optional[str]): The Matrix user ID (optional).

    Inherits:
        _AnsibleMatrixObject: Provides Matrix ID formatting utilities
        AsyncClient: Provides core Matrix client functionality
    """

    def __init__(self, domain: str, uri: str, token: str, user: Optional[str] = None):
        _AnsibleMatrixObject.__init__(self, domain=domain)
        AsyncClient.__init__(
            self,
            homeserver=uri,
            user=self.login_to_id(user),
            device_id=ANSIBLE_MATRIX_DEVICE_ID
        )

        self.access_token = token

    async def sync(
            self,
            timeout: Optional[int] = 0,
            sync_filter: _FilterT = None,
            since: Optional[str] = None,
            full_state: Optional[bool] = None,
            set_presence: Optional[str] = None,
    ) -> Union[SyncResponse, SyncError]:
        if self.user is None:
            whoami: WhoamiResponse = await self.whoami()
            self.user_id = whoami.user_id
            self.user = whoami.user_id

        return await super(AnsibleMatrixClient, self).sync(
            timeout,
            sync_filter,
            since,
            full_state,
            set_presence,
        )

    async def is_same_image(self, image, image_mime_type, mxc_url) -> bool:
        file_stat = await aiofiles.os.stat(image)
        # server, media = mxc_url.replace("mxc://", "").split("/")
        try:
            resp = await self.download(mxc=mxc_url)  # , server, media)
            if isinstance(resp, DownloadError):
                raise AnsibleMatrixWarning(
                    f"Failed to download image from '{mxc_url}'. "
                    f"Failure status {resp.status_code} and reason: {resp.message}",
                    orig_exc=resp
                )
        except AttributeError as e:
            raise AnsibleMatrixWarning(
                f"Failed to download image from '{mxc_url}'. Failure details: {e}",
                orig_exc=e
            )

        if file_stat.st_size == len(resp.body) \
                and image_mime_type == resp.content_type \
                and os.path.basename(image) in resp.filename:
            return True
        return False

    async def upload_image_if_new(
            self,
            in_image: Optional[str],
            old_mxc_url: Optional[str]) -> Optional[UploadResponse]:
        if in_image is None:
            return None

        url_mime = None
        tmp = TemporaryDirectory()
        if in_image.startswith("http"):
            in_image, url_mime = url2file(in_image, tmp)

        image, image_mime_type = if_svg_convert_to_png(in_image, detect_mime_type(in_image, url_mime), tmp)

        if old_mxc_url is not None and \
                await self.is_same_image(image, image_mime_type, old_mxc_url):
            return None

        file_stat = await aiofiles.os.stat(image)

        async with aiofiles.open(image, "r+b") as f:
            resp, maybe_keys = await self.upload(
                f,
                content_type=image_mime_type,  # image/jpeg
                filename=os.path.basename(image),
                filesize=file_stat.st_size)

        if isinstance(resp, UploadResponse):
            return resp
        else:
            raise AnsibleMatrixError(
                f"Failed to upload image. Failure status {resp.status_code} and reason: {resp.message}")

    # async def download_mxc(
    #         self,
    #         url: str,
    #         filename: Optional[str] = None,
    #         allow_remote: bool = True,
    # ) -> Union[DownloadResponse, DownloadError]:
    #     from nio.api import MATRIX_MEDIA_API_PATH
    #     query_parameters = {
    #         "allow_remote": "true" if allow_remote else "false",
    #     }
    #     end = ""
    #     if filename:
    #         end = filename
    #
    #     http_method = "GET"
    #     path = Api._build_path(["download", url, end], query_parameters, MATRIX_MEDIA_API_PATH)
    #
    #     return await self._send(
    #         DownloadResponse, http_method, path, timeout=0,
    #     )


def dicts_intersection(x: Dict, y: Dict) -> Dict:
    return {k: x[k] for k in x if k in y and x[k] == y[k]}


def dict_subtract(origin: Dict, what: Dict) -> Dict:
    new_origin = deepcopy(origin)
    for k in what.keys():
        new_origin.pop(k)
    return new_origin


def list_subtract(x: set, y: set) -> list:
    return [item for item in x if item not in y]
