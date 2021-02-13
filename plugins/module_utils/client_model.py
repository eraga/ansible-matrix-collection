from nio import *
from nio.api import MATRIX_MEDIA_API_PATH

ANSIBLE_MATRIX_DEVICE_ID = "ansible-eraga-matrix-module"


class _AnsibleMatrixObject(object):
    def __init__(self, domain: str = ""):
        self.domain = domain

    def login_to_id(self, login: str) -> str:
        return "@{}:{}".format(login, self.domain)


class AnsibleMatrixClient(_AnsibleMatrixObject, AsyncClient):
    def __init__(self, domain: str, uri: str, token: str, user: str):
        _AnsibleMatrixObject.__init__(self, domain=domain)
        AsyncClient.__init__(
            self,
            homeserver=uri,
            user=self.login_to_id(user),
            device_id=ANSIBLE_MATRIX_DEVICE_ID
        )

        self.access_token = token

    # async def download_mxc(
    #         self,
    #         url: str,
    #         filename: Optional[str] = None,
    #         allow_remote: bool = True,
    # ) -> Union[DownloadResponse, DownloadError]:
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
