import asyncio

from markdown import markdown

from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import *
from ansible_collections.eraga.matrix.plugins.module_utils.errors import AnsibleMatrixError


class AnsibleMatrixRoom(_AnsibleMatrixObject):
    def __init__(self,
                 matrix_client: AnsibleMatrixClient,
                 matrix_room_alias: str,
                 changes: Dict[str, Any] = ()):
        super().__init__(domain=matrix_client.domain)
        self.changes = changes
        self.matrix_client = matrix_client

        self.matrix_room_alias = matrix_room_alias

        self.matrix_room_fq_alias = "#{}:{}".format(matrix_room_alias, self.domain)

        self.matrix_room: Optional[MatrixRoom] = None

        self.matrix_room_id = None

    async def __aenter__(self):
        room_alias_response = await self.matrix_client.room_resolve_alias(self.matrix_room_fq_alias)
        # Sync encryption keys with the server
        # Required for participating in encrypted rooms
        if self.matrix_client.should_upload_keys:
            await self.matrix_client.keys_upload()

        if isinstance(room_alias_response, RoomResolveAliasResponse):
            self.matrix_room_id = room_alias_response.room_id

            await self.matrix_client.sync()

            if self.matrix_room_id in self.matrix_client.rooms:
                self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]
        else:
            self.matrix_room_id = None

        return self

    async def __aexit__(self, *args):
        await self.matrix_client.close()

    async def set_topic(self, topic: Optional[str]):
        if topic is None:
            return

        if topic == self.matrix_room.topic:
            return

        self.changes['topic'] = {
            'old': self.matrix_room.topic,
            'new': topic
        }

        pl_result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.topic",
            content={"topic": topic}
        )

        if isinstance(pl_result, RoomPutStateError):
            raise AnsibleMatrixError(pl_result.__dict__)

        # logger.debug("{}: set topic to: {}", self.matrix_room_alias, topic)

    async def set_name(self, name: Optional[str]):
        if name is None:
            return

        if name == self.matrix_room.name:
            return

        self.changes['name'] = {
            'old': self.matrix_room.name,
            'new': name
        }

        pl_result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.name",
            content={"name": name}
        )

        if isinstance(pl_result, RoomPutStateError):
            raise AnsibleMatrixError(pl_result.__dict__)

    # async def set_federate(self, federate):
    #     pass

    async def set_visibility(self, visibility: Optional[str] = None):
        if visibility is None:
            return

        path = ["directory", "list", "room", self.matrix_room_id]
        path = Api._build_path(path)

        response = await self.matrix_client.send(
            "GET", path, None, headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        data = await response.json()

        if data['visibility'] != visibility:
            response = await self.matrix_client.send(
                "PUT", path, Api.to_json({"visibility": visibility}), headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(self.matrix_client.access_token)
                }
            )
            response.raise_for_status()
            self.changes['visibility'] = {
                'old': data['visibility'],
                'new': visibility
            }

    async def _become_room_admin(self, mxid):
        # self.changes['_become_room_admin'] = {}
        # self.changes['_become_room_admin']['mxid'] = mxid
        # self.changes['_become_room_admin']['users_keys'] = self.matrix_room.power_levels.users
        # self.changes['_become_room_admin']['mxid_level'] = self.matrix_room.power_levels.users[mxid]
        if mxid in self.matrix_room.power_levels.users.keys() \
                and self.matrix_room.power_levels.users[mxid] == 100:
            return

        path = "/_synapse/admin/v1/rooms/{}/make_room_admin".format(self.matrix_room_id)
        # path = "/_synapse/admin/v1/rooms/{}".format(self.matrix_room_id)
        method = "POST"
        # method = "GET"
        data = {
            "user_id": mxid
        }

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        response.raise_for_status()
        self.changes['room_admin'] = await response.text()

    async def set_encryption(self, encryption: bool):
        if encryption:
            if not self.matrix_room.encrypted:
                self.changes['encryption'] = {
                    'old': False,
                    'new': True
                }

                event_dict = EnableEncryptionBuilder().as_dict()

                pl_result = await self.matrix_client.room_put_state(
                    room_id=self.matrix_room_id,
                    event_type=event_dict["type"],
                    content=event_dict["content"],
                )

                if isinstance(pl_result, RoomPutStateError):
                    raise AnsibleMatrixError(pl_result.__dict__)
                else:
                    return
        else:
            if not self.matrix_room.encrypted:
                return
            else:
                raise AnsibleMatrixError("Once enabled, encryption cannot be disabled.")

    async def set_community(self, community):
        pass

    async def set_power_levels(self, content: Dict) -> RoomPutStateResponse:
        pl_result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.power_levels",
            content=content
        )
        if isinstance(pl_result, RoomPutStateError):
            raise AnsibleMatrixError("{}".format(pl_result.message))

        return pl_result

    async def set_power_level_overrides(self, content: Optional[Dict]):
        if content is None:
            return

        current_levels = self.matrix_room.power_levels.defaults.__dict__
        content_to_apply = {}
        for key in content:
            if key in current_levels.keys():
                if current_levels[key] != content[key]:
                    content_to_apply[key] = content[key]

        if not bool(content_to_apply):
            return

        content_to_apply['users'] = self.matrix_room.power_levels.users
        await self.set_power_levels(content_to_apply)
        self.changes['power_level_overrides'] = content_to_apply

    async def set_power_members(self, room_members: Optional[Dict[str, int]]):
        if room_members is None:
            # raise MatrixError("nonono")
            return

        power_members = {self.login_to_id(k): v for k, v in room_members.items()}
        power_members[self.matrix_room.creator] = 100

        not_changed = dicts_intersection(
            self.matrix_room.power_levels.users,
            power_members
        )

        if len(not_changed.keys()) == len(power_members.keys()):
            # raise MatrixError("{} == {}".format(not_changed.keys(), power_members.keys()))
            return

        old_users_set = set(self.matrix_room.users.keys())
        new_users_set = set(map(lambda it: self.login_to_id(it), room_members.keys()))
        new_users_set.add(self.matrix_room.creator)

        not_changed_users = set(old_users_set & new_users_set)
        kicked_users = list_subtract(old_users_set, not_changed_users)
        invited_users = list_subtract(new_users_set, not_changed_users)

        existing_members = self.matrix_room.power_levels.users

        # self.changes['users']['old_power_levels'] = deepcopy(self.matrix_room.power_levels.users)
        # self.changes['users']['changed_power_levels'] = dict_subtract(existing_members, not_changed)
        # self.changes['users']['invited_power_levels'] = dict_subtract(power_members, not_changed)
        # self.changes['users']['new_power_levels'] = power_members
        # self.changes['users']['kicked'] = kicked_users
        # self.changes['users']['invited'] = invited_users

        if self.matrix_room.creator in kicked_users:
            raise AnsibleMatrixError("Can't kick creator {}".format(self.matrix_room.creator))

        # do invites
        for mxid in invited_users:
            if mxid not in self.matrix_room.users.keys():
                await self.matrix_client.room_invite(self.matrix_room_id, mxid)

        # do kicks
        for mxid in kicked_users:
            await self.matrix_client.room_kick(self.matrix_room_id, mxid)

        # change power levels
        await self.set_power_levels(
            {
                "users": power_members
            }
        )

        self.changes['users'] = {}
        self.changes['users']['old_power_levels'] = deepcopy(self.matrix_room.power_levels.users)
        self.changes['users']['changed_power_levels'] = dict_subtract(existing_members, not_changed)
        self.changes['users']['invited_power_levels'] = dict_subtract(power_members, not_changed)
        self.changes['users']['new_power_levels'] = power_members
        self.changes['users']['kicked'] = kicked_users
        self.changes['users']['invited'] = invited_users

    async def matrix_room_update(
            self,
            visibility: Optional[str] = None,
            name: Optional[str] = None,
            topic: Optional[str] = None,
            federate: bool = False,
            preset: Optional[RoomPreset] = None,
            room_members: Optional[Dict[str, int]] = None,
            encrypt: bool = False,
            power_level_override: Optional[Dict[str, Any]] = None
    ):
        await self.matrix_client.sync()
        if self.matrix_room_id not in self.matrix_client.rooms:
            raise AnsibleMatrixError("Not in room {}, can't manage it".format(self.matrix_room_fq_alias))

        self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]
        await self._become_room_admin(self.matrix_client.user)
        await self.set_power_members(room_members)
        await self.matrix_client.sync()

        await asyncio.gather(
            self.set_topic(topic),
            self.set_name(name),
            self.set_encryption(encrypt),
            self.set_visibility(visibility),
            self.set_power_level_overrides(power_level_override)
        )

    def matrix_room_exists(self) -> bool:
        # if self.matrix_room_id is not None and self.matrix_room is None:
        #     await self.matrix_client.sync(timeout=30000)
        return self.matrix_room_id is not None

    async def matrix_room_create(
            self,
            visibility: str = "private",
            name: Optional[str] = None,
            topic: Optional[str] = None,
            federate: bool = False,
            preset: Optional[str] = None,
            room_members: Optional[Dict[str, int]] = None,
            encrypt: bool = False,
            power_level_override: Optional[Dict[str, Any]] = None
    ):
        invitees: List[str] = []
        if room_members is not None:
            invitees = list(map(lambda it: self.login_to_id(it), room_members.keys()))

            if self.matrix_client.user_id in invitees:
                invitees.remove(self.matrix_client.user_id)

        room_preset = None
        if preset is not None:
            room_preset = RoomPreset(preset)

        result = await self.matrix_client.room_create(
            name=name,
            alias=self.matrix_room_alias,
            visibility=RoomVisibility(visibility),
            topic=topic,
            preset=room_preset,
            federate=federate,
            invite=invitees,
            power_level_override=power_level_override
        )
        if isinstance(result, RoomCreateError):
            if isinstance(result.status_code, str) and result.status_code == "M_ROOM_IN_USE":
                raise AnsibleMatrixError("can't create room '{}': already exists".format(self.matrix_room_alias))
            else:
                raise AnsibleMatrixError("can't create room '{}':".format(self.matrix_room_alias, result))

        self.matrix_room_id = result.room_id

        await self.matrix_client.sync()
        self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]

        await self.set_power_members(room_members)
        await self.set_encryption(encrypt)

        await self.matrix_client.sync()
        self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]

        self.changes['created'] = True

    async def send_text(self, message: str, notice: bool = False):
        message_type = "m.notice" if notice else "m.text"

        content = {
            "msgtype": message_type,
            "format": "org.matrix.custom.html",
            "body": message,
            "formatted_body": markdown(message)
        }

        response = await self.matrix_client.room_send(
            self.matrix_room_id,
            message_type="m.room.message",
            content=content
        )

        if isinstance(response, ErrorResponse):
            raise AnsibleMatrixError(
                f"Failed to send message to {self.matrix_room_alias} due to {response.status_code}: {response.message}"
            )
        elif isinstance(response, RoomSendResponse):
            self.changes['event_id'] = response.event_id

    async def delete(self):
        path = "/_synapse/admin/v1/rooms/{}/delete".format(self.matrix_room_id)
        method = "POST"
        data = {
            "block": False,
            "purge": True
        }

        response = await self.matrix_client.send(
            method, path, Api.to_json(data), headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        response.raise_for_status()
        self.changes['delete'] = await response.json()

    def matrix_room_to_dict(self) -> dict:
        room = self.matrix_room
        room_dict = dict()
        room_dict['id'] = room.room_id
        room_dict['canonical_alias'] = room.canonical_alias
        room_dict['users'] = room.users.keys()
        room_dict['user_levels'] = list(
            map(lambda it: "{}: {}".format(it.user_id, it.power_level), room.users.values())
        )
        room_dict['name'] = room.name
        room_dict['topic'] = room.topic
        room_dict['creator'] = room.creator

        # if room.power_levels:
        #     room_dict['power_levels'] = room.power_levels.__dict__
        #     if room.power_levels.defaults:
        #         levels_defaults = room.power_levels.defaults.__dict__
        #         room_dict['power_levels']['defaults'] = levels_defaults
        #
        #     room_dict['can'] = {}
        #     room_dict['can']['send'] = room.power_levels.can_user_send_message(self.matrix_client.user)
        #     room_dict['can']['state_name'] = room.power_levels.can_user_send_state(self.matrix_client.user, "m.room.name")
        #     room_dict['can']['state_levels'] = room.power_levels.can_user_send_state(self.matrix_client.user, "m.room.power_levels")
        #     room_dict['can']['ban'] = room.power_levels.can_user_ban(self.matrix_client.user)

        room_dict['federate'] = room.federate
        room_dict['room_version'] = room.room_version
        room_dict['history_visibility'] = room.history_visibility
        return room_dict
