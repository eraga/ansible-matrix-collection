import asyncio
from typing import Set

from markdown import markdown
from nio.responses import WhoamiResponse

from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import *
from ansible_collections.eraga.matrix.plugins.module_utils.community import AnsibleMatrixCommunity
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

        self.communities: Set[str] = set()

    async def __aenter__(self):
        self.matrix_client.sync()
        room_alias_response = await self.matrix_client.room_resolve_alias(self.matrix_room_fq_alias)

        # raise AnsibleMatrixError((await self.matrix_client.whoami()).user_id)
        # Sync encryption keys with the server
        # Required for participating in encrypted rooms
        if self.matrix_client.should_upload_keys:
            await self.matrix_client.keys_upload()

        if isinstance(room_alias_response, RoomResolveAliasResponse):
            self.matrix_room_id = room_alias_response.room_id

            if self.matrix_room_id in self.matrix_client.invited_rooms:
                self.matrix_client.room_invite()

            # Check if already in room
            rooms_resp = await self.matrix_client.joined_rooms()

            if isinstance(rooms_resp, JoinedRoomsError):
                raise AnsibleMatrixError(f"Couldn't get joined rooms: {rooms_resp.status_code} {rooms_resp.message}")
            elif room_alias_response.room_id in rooms_resp.rooms:
                pass
            else:
                # Try to join room
                join_resp = await self.matrix_client.join(self.matrix_room_id)

                # If successful, return, changed=true
                if isinstance(join_resp, JoinResponse):
                    self.changes['joined'] = join_resp.room_id
                    pass
                # else:
                    # self.matrix_client.user_id = self.matrix_client.login_to_id(self.matrix_client.user)
                    # self.changes['debug'] = await self.matrix_client.get_profile()
                    # pass
                    # raise AnsibleMatrixError(f"Room exists, but couldn't join: {join_resp}. Profile: {self.matrix_client.user_id}")

            sync_response = await self.matrix_client.sync()

            if self.matrix_room_id in self.matrix_client.rooms:
                self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]
                latest_event: Optional[Event] = sync_response.rooms.join[self.matrix_room_id].timeline.events.pop()
                await self.matrix_client.room_read_markers(self.matrix_room_id, latest_event.event_id)
                # self.changes['latest_event'] = latest_event
            else:
                pass
                # raise AnsibleMatrixError(
                #     f"{self.matrix_room_id} not found in {self.matrix_client.rooms} for alias {self.matrix_room_fq_alias}")
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

        pl_result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.name",
            content={"name": name}
        )

        if isinstance(pl_result, RoomPutStateError):
            raise AnsibleMatrixError(pl_result.__dict__)

        self.changes['name'] = {
            'old': self.matrix_room.name,
            'new': name
        }

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

    # async def set_communities(self, localparts: Optional[List[str]]):
    #     if localparts is None:
    #         return
    #
    #     communities_changes: List[Dict[str, Any]] = []
    #     for localpart in localparts:
    #         community_changes: Dict[str, Any] = {}
    #
    #         community = AnsibleMatrixCommunity(
    #             matrix_client=self.matrix_client,
    #             localpart=localpart,
    #             changes=community_changes
    #         )
    #
    #         async with community:
    #             if community.summary is None:
    #                 continue
    #
    #             if community.has_room(self.matrix_room_id):
    #                 self.communities.add(community.group_id)
    #                 continue
    #
    #             await community.add_room(self.matrix_room_id)
    #
    #             if community_changes:
    #                 communities_changes.append(community_changes)
    #
    #     if communities_changes:
    #         self.changes['community'] = communities_changes

    async def set_power_levels(self, content: Dict) -> RoomPutStateResponse:
        result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.power_levels",
            content=content
        )
        if isinstance(result, RoomPutStateError):
            raise AnsibleMatrixError(f"{result.status_code}: '{result.message}' when setting m.room.power_levels with {content}")

        return result

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
            return

        power_members = {self.login_to_id(k): v for k, v in room_members.items()}
        power_members[self.matrix_client.user] = 100

        # We can't demote Admins :(
        for user in self.matrix_room.power_levels.users:
            if self.matrix_room.power_levels.users[user] == 100:
                power_members[user] = 100

        not_changed = dicts_intersection(
            self.matrix_room.power_levels.users,
            power_members
        )

        if len(not_changed.keys()) == len(power_members.keys()):
            return

        old_users_set = set(self.matrix_room.users.keys())
        new_users_set = set(map(lambda it: self.login_to_id(it), power_members.keys()))
        new_users_set.add(self.matrix_room.own_user_id)

        not_changed_users = set(old_users_set & new_users_set)
        kicked_users = list_subtract(old_users_set, not_changed_users)
        invited_users = list_subtract(new_users_set, not_changed_users)

        existing_members = self.matrix_room.power_levels.users

        # self.changes['users'] = {}
        # self.changes['users']['old_users_set'] = old_users_set
        # self.changes['users']['new_users_set'] = new_users_set
        # self.changes['users']['old_power_levels'] = deepcopy(self.matrix_room.power_levels.users)
        # self.changes['users']['changed_power_levels'] = dict_subtract(existing_members, not_changed)
        # self.changes['users']['invited_power_levels'] = dict_subtract(power_members, not_changed)
        # self.changes['users']['new_power_levels'] = power_members
        # self.changes['users']['kicked'] = kicked_users
        # self.changes['users']['invited'] = invited_users
        #
        # raise AnsibleMatrixError("Shit!!")

        if self.matrix_client.user in kicked_users:
            raise AnsibleMatrixError("Can't kick self: {}".format(self.matrix_client.user))

        # if self.matrix_room.creator in kicked_users:
        #     raise AnsibleMatrixError("Can't kick creator {}".format(self.matrix_room.creator))

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

    async def set_avatar(self, in_image: Optional[str]):
        resp = await self.matrix_client.upload_image_if_new(in_image, self.matrix_room.room_avatar_url)

        if resp is None:
            return

        pl_result = await self.matrix_client.room_put_state(
            room_id=self.matrix_room_id,
            event_type="m.room.avatar",
            content={"url": resp.content_uri}
        )

        if isinstance(pl_result, RoomPutStateError):
            raise AnsibleMatrixError(pl_result.__dict__)

        self.changes['avatar_url'] = {}
        self.changes['avatar_url']['old'] = self.matrix_room.room_avatar_url
        self.changes['avatar_url']['new'] = resp.content_uri

    async def matrix_room_update(
            self,
            visibility: Optional[str] = None,
            name: Optional[str] = None,
            topic: Optional[str] = None,
            avatar: Optional[str] = None,
            federate: bool = False,
            preset: Optional[RoomPreset] = None,
            room_members: Optional[Dict[str, int]] = None,
            encrypt: bool = False,
            power_level_override: Optional[Dict[str, Any]] = None,
            communities: Optional[List[str]] = None
    ):
        # self.matrix_client.login()
        await self.sync_details()

        # await self._become_room_admin(self.matrix_client.user)
        await self.set_power_members(room_members)
        await self.sync_details()

        await asyncio.gather(
            self.set_encryption(encrypt),
            self.set_avatar(avatar),
            self.set_topic(topic),
            self.set_name(name),
            self.set_visibility(visibility),
            self.set_power_level_overrides(power_level_override),
            # self.set_communities(communities),
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
            avatar: Optional[str] = None,
            federate: bool = False,
            preset: Optional[str] = None,
            room_members: Optional[Dict[str, int]] = None,
            encrypt: bool = False,
            power_level_override: Optional[Dict[str, Any]] = None,
            communities: Optional[List[str]] = None
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
            elif result.message == "Cannot invite so many users at once":
                raise AnsibleMatrixWarning(result.__str__())
            else:
                raise AnsibleMatrixError("can't create room '{}': {}".format(self.matrix_room_alias, result))

        self.matrix_room_id = result.room_id

        await self.sync_details()

        await self.set_encryption(encrypt)
        await self.set_avatar(avatar)
        await self.set_power_members(room_members)
        # await self.set_communities(communities)

        await self.sync_details()

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

    async def delete(self, block: bool = False, purge: bool = False):
        path = "/_synapse/admin/v1/rooms/{}/delete".format(self.matrix_room_id)
        method = "POST"
        data = {
            "block": block,
            "purge": purge
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
        if self.matrix_room is None:
            return {}
        room = self.matrix_room
        room_dict = dict()
        room_dict['id'] = self.matrix_room_id
        room_dict['canonical_alias'] = room.canonical_alias
        room_dict['users'] = room.users.keys()
        room_dict['user_levels'] = list(
            map(lambda it: "{}: {}".format(it.user_id, it.power_level), room.users.values())
        )
        room_dict['name'] = room.name
        room_dict['topic'] = room.topic
        # room_dict['creator'] = room.own_user_id

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

    async def sync_details(self):
        if self.matrix_room_id not in self.matrix_client.rooms:
            await self.room_admin_get_details()
            if self.matrix_room is None:
                raise AnsibleMatrixError("Not in room {}, can't manage it".format(self.matrix_room_fq_alias))
        else:
            self.matrix_room = self.matrix_client.rooms[self.matrix_room_id]

    async def room_admin_get_details(self):
        # GET /_synapse/admin/v1/rooms/<room_id>
        path = "/_synapse/admin/v1/rooms/{}".format(self.matrix_room_id)
        method = "GET"

        response = await self.matrix_client.send(
            method, path, None, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.matrix_client.access_token)
            }
        )
        response.raise_for_status()
        room_info = await response.json()

        self.matrix_room = MatrixRoom(
            self.matrix_room_id,
            self.matrix_client.user,
            room_info['encryption']
        )

        self.matrix_room.name = room_info['name']
        self.matrix_room.room_avatar_url = room_info['avatar']
        self.matrix_room.topic = room_info['topic']
        self.matrix_room.canonical_alias = room_info['canonical_alias']
        # self.matrix_room.creator = room_info['creator']
        self.matrix_room.federate = room_info['federatable']
        # self.matrix_room = room_info['public']
        self.matrix_room.join_rule = room_info['join_rules']
        self.matrix_room.guest_access = room_info['guest_access']
        self.matrix_room.history_visibility = room_info['history_visibility']

        #
        # {
        #     "room_id": "!mscvqgqpHYjBGDxNym:matrix.org",
        #     "name": "Music Theory",
        #     "avatar": "mxc://matrix.org/AQDaVFlbkQoErdOgqWRgiGSV",
        #     "topic": "Theory, Composition, Notation, Analysis",
        #     "canonical_alias": "#musictheory:matrix.org",
        #     "joined_members": 127,
        #     "joined_local_members": 2,
        #     "joined_local_devices": 2,
        #     "version": "1",
        #     "creator": "@foo:matrix.org",
        #     "encryption": null,
        #     "federatable": true,
        #     "public": true,
        #     "join_rules": "invite",
        #     "guest_access": null,
        #     "history_visibility": "shared",
        #     "state_events": 93534
        # }
