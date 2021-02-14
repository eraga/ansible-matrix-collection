import asyncio

from aiohttp import ClientResponseError
from dataclasses_json import dataclass_json, Undefined

from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import *


@dataclass_json(undefined=Undefined.EXCLUDE)
@dataclass()
class AnsibleMatrixCommunityProfile(Convertable):
    name: Optional[str] = None
    short_description: Optional[str] = None
    long_description: Optional[str] = None
    avatar_url: Optional[str] = None
    is_public: Optional[str] = None
    is_openly_joinable: Optional[str] = None


@dataclass_json(undefined=Undefined.EXCLUDE)
@dataclass()
class AnsibleMatrixCommunityUsers(Convertable):
    users: Optional[List[Any]] = None
    roles: Optional[Dict[str, Any]] = None
    total_user_count_estimate: int = 0


@dataclass_json(undefined=Undefined.EXCLUDE)
@dataclass()
class AnsibleMatrixCommunityRooms(Convertable):
    rooms: Optional[List[Any]] = None
    categories: Optional[Dict[str, Any]] = None
    total_room_count_estimate: int = 0


@dataclass_json(undefined=Undefined.EXCLUDE)
@dataclass()
class AnsibleMatrixCommunitySummary(Convertable):
    profile: Optional[AnsibleMatrixCommunityProfile] = None
    # users_section: Optional[AnsibleMatrixCommunityUsers] = None
    # rooms_section: Optional[AnsibleMatrixCommunityRooms] = None

    rooms: Optional[Dict[str, Any]] = None
    rooms_list: List[str] = field(default_factory=list)

    users: Optional[Dict[str, Any]] = None
    users_list: List[str] = field(default_factory=list)

    invited_users: Optional[Dict[str, Any]] = None
    invited_users_list: List[str] = field(default_factory=list)


# noinspection PyProtectedMember
class AnsibleMatrixCommunity(_AnsibleMatrixObject):
    def __init__(self,
                 matrix_client: AnsibleMatrixClient,
                 localpart: str,
                 changes: Dict[str, Any] = ()):
        super(AnsibleMatrixCommunity, self).__init__(domain=matrix_client.domain)
        self.matrix_client = matrix_client
        self.localpart = localpart
        self.changes = changes
        self.summary: Optional[AnsibleMatrixCommunitySummary] = None

    @property
    def profile(self) -> Optional[AnsibleMatrixCommunityProfile]:
        if self.summary is None:
            return None

        return self.summary.profile

    async def __aenter__(self):
        await self._load_community()
        return self

    async def __aexit__(self, *args):
        await self.matrix_client.close()

    async def _load_community(self):
        # GET /_matrix/client/r0/groups/{}/invited_users HTTP/1.1
        # GET /_matrix/client/r0/groups/{}/summary HTTP/1.1
        # GET /_matrix/client/r0/groups/{}/profile HTTP/1.1
        group = self.localpart_to_mx_group(self.localpart)
        path = Api._build_path(["groups", group, "summary"])
        method = "GET"

        response = await self.matrix_client.send(
            method, path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        if response.status == 404:
            return None

        response.raise_for_status()
        summary = await response.json()
        self.summary = AnsibleMatrixCommunitySummary.from_dict(summary)
        await self._load_community_rooms()
        await self._load_community_users()
        await self._load_community_invited_users()
        # await self._accept_invite("")

    async def _load_community_rooms(self):
        if self.summary is None:
            raise RuntimeError("You must init self.summary field first!")

        group = self.localpart_to_mx_group(self.localpart)
        path = Api._build_path(["groups", group, "rooms"])
        method = "GET"

        response = await self.matrix_client.send(
            method, path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()
        rooms = await response.json()
        self.summary.rooms = rooms
        self.summary.rooms_list = list(map(lambda it: it['room_id'], rooms['chunk']))

    async def _load_community_users(self):
        if self.summary is None:
            raise RuntimeError("You must init self.summary field first!")

        group = self.localpart_to_mx_group(self.localpart)
        path = Api._build_path(["groups", group, "users"])
        method = "GET"

        response = await self.matrix_client.send(
            method, path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()
        users = await response.json()
        self.summary.users = users
        self.summary.users_list = list(map(lambda it: it['user_id'], users['chunk']))

    async def _load_community_invited_users(self):
        if self.summary is None:
            raise RuntimeError("You must init self.summary field first!")

        group = self.localpart_to_mx_group(self.localpart)
        path = Api._build_path(["groups", group, "invited_users"])
        method = "GET"

        response = await self.matrix_client.send(
            method, path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()
        invited_users = await response.json()
        self.summary.invited_users = invited_users
        self.summary.invited_users_list = list(map(lambda it: it['user_id'], invited_users['chunk']))

    async def _accept_invite(self, group_id: str):
        path = Api._build_path(["groups", group_id, "self", "accept_invite"])
        method = "PUT"

        response = await self.matrix_client.send(
            method, path, Api.to_json({}), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()

    async def _create(self, name: str):
        # POST /_matrix/client/r0/create_group HTTP/1.1
        # {"localpart":"test","profile":{"name":"Test Comm"}}
        path = Api._build_path(["create_group"])
        method = "POST"
        data = {
            "localpart": self.localpart,
            "profile": {
                "name": name
            }
        }
        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()
        await self._load_community()

    async def _update_profile(self, content: Dict[str, any]):
        group = self.localpart_to_mx_group(self.localpart)
        path = Api._build_path(["groups", group, "profile"])
        method = "POST"
        response = await self.matrix_client.send(
            method, path, Api.to_json(content), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()
        await self._load_community()

    async def add_room(self, room_id: str, visibility: str = "private"):
        group = self.localpart_to_mx_group(self.localpart)
        method = "PUT"
        path = ["groups", group, "admin", "rooms", room_id]
        #
        data = {"m.visibility": {"type": visibility}}
        path = Api._build_path(path)

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()

        if 'rooms' not in self.changes:
            self.changes['rooms'] = {}

        if 'added' not in self.changes['rooms']:
            self.changes['rooms']['added'] = []

        self.changes['rooms']['added'].append(room_id)
        pass

    async def remove_room(self, room_id: str):
        group = self.localpart_to_mx_group(self.localpart)
        method = "DELETE"
        path = ["groups", group, "admin", "rooms", room_id]
        data = {}
        path = Api._build_path(path)

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()

        if 'rooms' not in self.changes:
            self.changes['rooms'] = {}

        if 'removed' not in self.changes['rooms']:
            self.changes['rooms']['removed'] = []

        self.changes['rooms']['removed'].append(room_id)
        pass

    async def remove(self, mxid: str):
        if mxid not in (self.summary.users_list + self.summary.invited_users_list):
            return

        group = self.localpart_to_mx_group(self.localpart)
        method = "PUT"
        path = ["groups", group, "admin", "users", "remove", mxid]
        data = {}
        path = Api._build_path(path)

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()

        if 'members' not in self.changes:
            self.changes['members'] = {}

        if 'removed' not in self.changes['members']:
            self.changes['members']['removed'] = []

        self.changes['members']['removed'].append(mxid)

    async def invite(self, mxid: str):
        if mxid in self.summary.users_list or mxid in self.summary.invited_users_list:
            return

        group = self.localpart_to_mx_group(self.localpart)
        method = "PUT"
        path = ["groups", group, "admin", "users", "invite", mxid]
        data = {"user_id": mxid}
        path = Api._build_path(path)

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        response.raise_for_status()

        if 'members' not in self.changes:
            self.changes['members'] = {}

        if 'invited' not in self.changes['members']:
            self.changes['members']['invited'] = []

        self.changes['members']['invited'].append(mxid)

    async def set_members(self, members: Optional[List[str]]):
        if members is None:
            return

        if self.matrix_client.user not in members:
            members.append(self.matrix_client.user)

        old_users_set = set(self.summary.users_list + self.summary.invited_users_list)
        new_users_set = set(map(lambda it: self.login_to_id(it), members))
        not_changed_users = set(old_users_set & new_users_set)
        kicked_users = list_subtract(old_users_set, not_changed_users)
        invited_users = list_subtract(new_users_set, not_changed_users)

        # self.changes['old_users_set'] = old_users_set
        # self.changes['new_users_set'] = new_users_set
        # self.changes['not_changed_users'] = not_changed_users
        # self.changes['kicked_users'] = kicked_users
        # self.changes['invited_users'] = invited_users

        for member in invited_users:
            await self.invite(member)

        for member in kicked_users:
            await self.remove(member)

    async def set_rooms(self, rooms: Optional[List[str]]):
        if rooms is None or len(rooms) == 0:
            return

        for alias in rooms:
            if alias not in self.summary.rooms_list:
                await self.add_room(self.room_alias_to_mx_alias(alias))

    async def set_name(self, name: Optional[str]):
        if name is None or name == self.profile.name:
            return

        await self._update_profile({
            "name": name
        })

    async def set_description(self, description: Optional[str]):
        if description is None or description == self.profile.short_description:
            return

        await self._update_profile({
            "short_description": description
        })

        self.changes["description"] = {}
        self.changes["description"]["old"] = self.profile.short_description
        self.changes["description"]["new"] = description

    async def set_join_policy(self, policy: Optional[str]):
        # PUT /_matrix/client/r0/groups/%2Btest%3Aeraga.net/settings/m.join_policy HTTP/1.1
        # todo
        # is_openly_joinable
        pass

    async def set_avatar(self, in_image: str):
        resp = await self.matrix_client.upload_image_if_new(in_image, self.profile.avatar_url)

        if resp is None:
            return

        await self._update_profile(content={
            "avatar_url": resp.content_uri
        })

        self.changes['avatar_url'] = {}
        self.changes['avatar_url']['old'] = self.profile.avatar_url
        self.changes['avatar_url']['new'] = resp.content_uri

    async def set_long_description(self, description):
        if description is None:
            return

        from markdown import markdown
        long_description = markdown(description)
        if long_description == self.profile.long_description:
            return

        await self._update_profile({
            "long_description": long_description
        })

        self.changes["long_description"] = {}
        self.changes["long_description"]["old"] = self.profile.long_description
        self.changes["long_description"]["new"] = long_description

    async def set_visibility(self, visibility):
        # todo
        # is_public
        pass

    async def update(self,
                     name: Optional[str] = None,
                     avatar: Optional[str] = None,
                     description: Optional[str] = None,
                     long_description: Optional[str] = None,
                     visibility: Optional[str] = None,
                     members: Optional[List[str]] = None,
                     rooms: Optional[List[str]] = None,
                     ):
        try:
            if self.profile is None:
                if name is None:
                    raise AnsibleMatrixError(f"{self.localpart} requires 'name' to be created")
                await self._create(name)

            await asyncio.gather(
                self.set_name(name),
                self.set_description(description),
                self.set_long_description(long_description),
                self.set_avatar(avatar),
                self.set_visibility(visibility),
                self.set_members(members),
                self.set_rooms(rooms),
            )

            await self._load_community()
        except ClientResponseError as e:
            raise AnsibleMatrixError(f"{e.status} {e.message}")
        return

    async def delete(self):
        # https://github.com/matrix-org/synapse/blob/master/docs/admin_api/delete_group.md
        path = "/_synapse/admin/v1/delete_group/{}".format(self.localpart_to_mx_group(self.localpart))
        method = "POST"
        data = {}

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )

        if response.status == 404:
            return

        response.raise_for_status()
        self.changes['delete'] = await response.json()
