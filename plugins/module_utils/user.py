import os
import tempfile

import aiofiles
import aiofiles.os

from dataclasses import asdict, dataclass
from dataclasses_json import dataclass_json, Undefined

from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import *
from ansible_collections.eraga.matrix.plugins.module_utils.errors import MatrixError
from ansible_collections.eraga.matrix.plugins.module_utils.utils import detect_mime_type, url2file

from cairosvg import svg2png


@dataclass_json(undefined=Undefined.EXCLUDE)
@dataclass
class AnsibleMatrixAccount(object):
    mxid: Optional[str] = None
    displayname: Optional[str] = None
    threepids: Optional[List[Dict[str, str]]] = None
    avatar_url: Optional[str] = None
    admin: bool = False
    deactivated: bool = False
    password_hash: Optional[str] = None
    creation_ts: int = 0
    appservice_id: Optional[str] = None
    consent_server_notice_sent: Optional[str] = None
    consent_version: Optional[str] = None

    def dict(self) -> dict:
        result = dict()
        self_dict = asdict(self)

        for k in self_dict:
            if isinstance(self_dict[k], dict):
                result[k] = self.__getattribute__(k).dict()
            elif isinstance(self_dict[k], list):
                result[k] = list(map(AnsibleMatrixAccount.__map_dict__, self.__getattribute__(k))
                                 )
            elif self_dict[k] is not None:
                result[k] = self_dict[k]

        return result

    @staticmethod
    def __map_dict__(it):
        if isinstance(it, AnsibleMatrixAccount):
            return it.dict()

        return it


class AnsibleMatrixUser(_AnsibleMatrixObject):

    def __init__(self,
                 matrix_client: AnsibleMatrixClient,
                 login: str,
                 changes: Dict[str, Any] = ()
                 ):
        super().__init__(domain=matrix_client.domain)
        self.mxid = self.login_to_id(login)
        self.matrix_client = matrix_client
        self.changes = changes
        self._api_user_path = "/_synapse/admin/v2/users/{}".format(self.mxid)
        self.account: Optional[AnsibleMatrixAccount] = None

    async def __aenter__(self):
        await self._load_account()

        return self

    async def __aexit__(self, *args):
        await self.matrix_client.close()

    async def _load_account(self):
        # method = "POST"
        method = "GET"
        # data = {
        #     "user_id": mxid
        # }

        response = await self.matrix_client.send(
            method, self._api_user_path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        if 400 <= response.status != 404:
            response.raise_for_status()

        self.account = AnsibleMatrixAccount.from_dict(await response.json())
        self.account.mxid = self.mxid
        # self.changes['room_admin'] =

    async def _update_account(self, content):
        if self.account is None or not bool(content):
            return

        method = "PUT"

        response = await self.matrix_client.send(
            method, self._api_user_path, Api.to_json(content), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        response.raise_for_status()

    async def set_displayname(self, displayname: Optional[str] = None):
        if displayname is None or self.account.displayname == displayname:
            return

        await self._update_account(content={
            "displayname": displayname
        })

        self.changes['displayname'] = {}
        self.changes['displayname']['old'] = self.account.displayname
        self.changes['displayname']['new'] = displayname

    async def set_admin(self, admin: Optional[bool] = None):
        if admin is None or self.account.admin == admin:
            return

        await self._update_account(content={
            "admin": admin
        })

        self.changes['admin'] = {}
        self.changes['admin']['old'] = self.account.admin
        self.changes['admin']['new'] = admin

    async def set_deactivated(self, deactivated: Optional[bool] = None):
        if deactivated is None or self.account.deactivated == deactivated:
            return

        await self._update_account(content={
            "deactivated": deactivated
        })

        self.changes['deactivated'] = {}
        self.changes['deactivated']['old'] = self.account.deactivated
        self.changes['deactivated']['new'] = deactivated

    async def upload_avatar(self, in_image: Optional[str]):
        if in_image is None:
            return
        url_mime = None
        if in_image.startswith("http"):
            in_image, url_mime = url2file(in_image)

        mime_type = detect_mime_type(in_image, url_mime)

        image = in_image

        if "image/svg" in mime_type:
            tf = tempfile.NamedTemporaryFile(prefix=os.path.basename(in_image), suffix='.png')
            with open(in_image, "rb") as image_file:
                svg2png(file_obj=image_file, write_to=tf.name, output_height=600)
            image = tf.name
            mime_type = detect_mime_type(image)

        file_stat = await aiofiles.os.stat(image)

        if self.account.avatar_url is not None:
            server, media = self.account.avatar_url.replace("mxc://", "").split("/")
            print(server)
            print(media)
            resp = await self.matrix_client.download(server, media)
            if isinstance(resp, DownloadError):
                raise MatrixError(
                    f"Failed to download image. Failure status {resp.status_code} and reason: {resp.message}")

            if file_stat.st_size == len(resp.body) \
                    and mime_type == resp.content_type \
                    and os.path.basename(in_image) in resp.filename:
                return

        async with aiofiles.open(image, "r+b") as f:
            resp, maybe_keys = await self.matrix_client.upload(
                f,
                content_type=mime_type,  # image/jpeg
                filename=os.path.basename(image),
                filesize=file_stat.st_size)

        if isinstance(resp, UploadResponse):
            # print("Image was uploaded successfully to server. ")
            await self._update_account(content={
                "avatar_url": resp.content_uri
            })
            self.changes['avatar_url'] = {}
            self.changes['avatar_url']['old'] = self.account.avatar_url
            self.changes['avatar_url']['new'] = resp.content_uri

        else:
            raise MatrixError(f"Failed to upload image. Failure status {resp.status_code} and reason: {resp.message}")

    async def update(
            self,
            avatar: Optional[str] = None,
            displayname: Optional[str] = None,
            admin: Optional[bool] = None,
    ):
        # self.changes['print'] = avatar
        await self.upload_avatar(avatar)
        await self.set_displayname(displayname)
        await self.set_admin(admin)
        await self._load_account()

