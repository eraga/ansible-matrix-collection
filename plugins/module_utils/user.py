from dataclasses import asdict, dataclass
from dataclasses_json import dataclass_json, Undefined

from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import *


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
        resp = await self.matrix_client.upload_image_if_new(in_image, self.account.avatar_url)

        if resp is None:
            return

        await self._update_account(content={
            "avatar_url": resp.content_uri
        })

        self.changes['avatar_url'] = {}
        self.changes['avatar_url']['old'] = self.account.avatar_url
        self.changes['avatar_url']['new'] = resp.content_uri

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
