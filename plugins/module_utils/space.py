from typing import Dict, List, Optional

from aiohttp import ClientResponseError

from ansible_collections.eraga.matrix.plugins.module_utils.errors import AnsibleMatrixError


# from matrix_client.api import MatrixHttpApi

class AnsibleMatrixSpace:
    def __init__(self, matrix_client, localpart: str, changes: Dict):
        self.matrix = matrix_client
        self.localpart = localpart
        self.space_id = f"!{localpart}:{matrix_client.domain}"
        self.changes = changes

    async def exists(self) -> bool:
        try:
            await self.matrix.room_get_state(self.space_id)
            return True
        except:
            return False

    async def create_or_update(self, **kwargs):
        try:
            exists = await self.exists()

            if not exists:
                # Create space with proper creation content
                creation_content = {
                    "type": "m.space",
                    "room_version": "9"  # Spaces work best with room version 9
                }
                response = await self.matrix.room_create(
                    room_id=self.space_id,
                    visibility=kwargs.get('visibility', 'public'),
                    name=kwargs.get('name'),
                    topic=kwargs.get('topic'),
                    creation_content=creation_content
                )
                self.changes['created'] = True
                self.space_id = response['room_id']  # Store the created room ID

            if kwargs.get('name'):
                await self.matrix.room_set_displayname(self.space_id, kwargs['name'])

            if kwargs.get('topic'):
                await self.matrix.room_set_topic(self.space_id, kwargs['topic'])

            if kwargs.get('avatar'):
                await self.matrix.room_set_avatar(self.space_id, kwargs['avatar'])

            # Handle room additions
            if kwargs.get('rooms'):
                await self._update_rooms(kwargs['rooms'])

            # Handle member invites
            if kwargs.get('members'):
                await self._update_members(kwargs['members'])
        except ClientResponseError as e:
            raise AnsibleMatrixError(f"Failed to create/update space: {e.status} {e.message}")

    async def _update_rooms(self, rooms: List[str]):
        for room_id in rooms:
            # Convert alias to room_id if needed
            if room_id.startswith('#'):
                try:
                    room_info = await self.matrix.room_resolve_alias(room_id)
                    room_id = room_info['room_id']
                except:
                    raise AnsibleMatrixError(f"Could not resolve room alias: {room_id}")

            await self.matrix.send_state_event(
                self.space_id,
                "m.space.child",
                {
                    "via": [self.matrix.domain],
                    "suggested": True
                },
                state_key=room_id
            )

    async def _update_members(self, members: List[str]):
        # Invite members to the space
        for member in members:
            if not member.startswith("@"):
                member = f"@{member}:{self.matrix.domain}"
            await self.matrix.invite_user(self.space_id, member)

    async def delete(self):
        if await self.exists():
            await self.matrix.room_delete(self.space_id)
            self.changes['deleted'] = True

    async def get_state(self) -> Dict:
        state = await self.matrix.room_get_state(self.space_id)
        return {
            'id': self.space_id,
            'name': state.get('name', ''),
            'topic': state.get('topic', ''),
            'avatar': state.get('avatar_url', ''),
            'members': [evt['state_key'] for evt in state if evt['type'] == 'm.room.member'],
            'rooms': [evt['state_key'] for evt in state if evt['type'] == 'm.space.child']
        }

    async def set_parent(self, parent_id: str):
        """Set this space as a child of another space"""
        await self.matrix.send_state_event(
            self.space_id,
            "m.space.parent",
            {
                "via": [self.matrix.domain],
                "canonical": True
            },
            state_key=parent_id
        )
