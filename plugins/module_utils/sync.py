"""Bring one user or one room to the wanted state through MatrixApi.

Users the server does not have are skipped: the sync never creates an
account, invites it anywhere or uploads anything for it.
"""
import asyncio
from copy import deepcopy
from typing import Any, Dict, List, Optional

from ansible_collections.eraga.matrix.plugins.module_utils.admin import MatrixApi, MatrixHttpError
from ansible_collections.eraga.matrix.plugins.module_utils.avatar import avatar_to_set
from ansible_collections.eraga.matrix.plugins.module_utils.errors import AnsibleMatrixError

ENCRYPTION = {"algorithm": "m.megolm.v1.aes-sha2"}
OWNER_LEVEL = 100


# -- users -------------------------------------------------------------------

async def sync_user(api: MatrixApi, login: str, displayname: Optional[str] = None,
                    avatar: Optional[str] = None, admin: Optional[bool] = None,
                    state: str = "present") -> Dict[str, Any]:
    mxid = api.mxid(login)
    result = {"login": login, "mxid": mxid, "exists": False, "changed": False, "changed_fields": {}}

    account = await api.account(mxid)
    if account is None:
        return result
    result["exists"] = True
    result["deactivated"] = bool(account.get("deactivated"))

    changes = result["changed_fields"]
    content: Dict[str, Any] = {}

    if state == "deactivated":
        if not account.get("deactivated"):
            content["deactivated"] = True
            changes["deactivated"] = {"old": False, "new": True}
    elif account.get("deactivated"):
        # A deactivated account keeps no profile worth syncing.
        return result
    else:
        if displayname is not None and account.get("displayname") != displayname:
            content["displayname"] = displayname
            changes["displayname"] = {"old": account.get("displayname"), "new": displayname}
        if admin is not None and bool(account.get("admin")) != admin:
            content["admin"] = admin
            changes["admin"] = {"old": bool(account.get("admin")), "new": admin}
        new_avatar = await avatar_to_set(api, avatar, account.get("avatar_url"))
        if new_avatar is not None:
            content["avatar_url"] = new_avatar
            changes["avatar_url"] = {"old": account.get("avatar_url"), "new": new_avatar}

    if content:
        await api.update_account(mxid, content)
        result["changed"] = True
    return result


# -- rooms -------------------------------------------------------------------

class RoomState:
    def __init__(self, events: List[Dict[str, Any]]):
        self.state: Dict[tuple, Dict[str, Any]] = {
            (e["type"], e.get("state_key", "")): e.get("content") or {} for e in events
        }

    def content(self, event_type: str, state_key: str = "") -> Dict[str, Any]:
        return self.state.get((event_type, state_key), {})

    def membership(self, mxid: str) -> Optional[str]:
        return self.content("m.room.member", mxid).get("membership")

    @property
    def members(self) -> Dict[str, str]:
        """Joined and invited users, the ones a room 'has'."""
        return {k: c.get("membership") for (t, k), c in self.state.items()
                if t == "m.room.member" and c.get("membership") in ("join", "invite")}

    @property
    def encrypted(self) -> bool:
        return bool(self.content("m.room.encryption"))


def wanted_power_levels(current: Dict[str, Any], me: str, members: Optional[Dict[str, int]],
                        overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Full m.room.power_levels content: the event replaces, never merges."""
    wanted = deepcopy(current)
    for key, value in (overrides or {}).items():
        wanted[key] = value
    if members is not None:
        users = dict(members)
        # Owners cannot be demoted by another owner, so keep them as they are.
        for mxid, level in current.get("users", {}).items():
            if level >= OWNER_LEVEL:
                users[mxid] = level
        users[me] = OWNER_LEVEL
        wanted["users"] = users
    return wanted


async def _room_members_wanted(api: MatrixApi, room_members: Optional[Dict[str, int]]):
    """Wanted mxid -> level, keeping only users the server has; and the rest."""
    if room_members is None:
        return None, []
    logins = list(room_members)
    mxids = [api.mxid(login) for login in logins]
    active = await asyncio.gather(*(api.is_active_user(m) for m in mxids))
    wanted = {m: int(room_members[login]) for login, m, ok in zip(logins, mxids, active) if ok}
    missing = [login for login, ok in zip(logins, active) if not ok]
    return wanted, missing


async def sync_room(api: MatrixApi, alias: str, name: Optional[str] = None, topic: Optional[str] = None,
                    avatar: Optional[str] = None, federate: bool = False, visibility: str = "private",
                    preset: Optional[str] = None, room_members: Optional[Dict[str, int]] = None,
                    power_level_override: Optional[Dict[str, Any]] = None, encrypt: bool = False,
                    state: str = "present", **_ignored) -> Dict[str, Any]:
    me = await api.me()
    fq_alias = alias if alias.startswith("#") else "#{}:{}".format(alias, api.client.domain)
    result: Dict[str, Any] = {"alias": fq_alias, "room_id": None, "changed": False, "changed_fields": {},
                              "absent_users": [], "refused": []}
    changes = result["changed_fields"]

    room_id = await api.resolve_alias(fq_alias)
    result["room_id"] = room_id

    if state == "absent":
        if room_id is not None:
            changes["deleted"] = await api.delete_room(room_id) or True
            result["changed"] = True
        return result

    wanted_members, result["absent_users"] = await _room_members_wanted(api, room_members)

    if room_id is None:
        content: Dict[str, Any] = {
            "room_alias_name": alias.lstrip("#").split(":")[0],
            "visibility": visibility,
            "creation_content": {"m.federate": federate},
        }
        if name is not None:
            content["name"] = name
        if topic is not None:
            content["topic"] = topic
        if preset is not None:
            content["preset"] = preset
        if power_level_override:
            content["power_level_content_override"] = power_level_override
        if encrypt:
            content["initial_state"] = [{"type": "m.room.encryption", "state_key": "", "content": ENCRYPTION}]
        room_id = await api.create_room(content)
        result["room_id"] = room_id
        changes["created"] = True
        result["changed"] = True
        if room_id is None:  # check mode: nothing to read back
            if wanted_members is not None:
                changes["invited"] = sorted(m for m in wanted_members if m != me)
            return result

    room = RoomState(await api.room_state(room_id))
    if room.membership(me) != "join":
        try:
            await api.join(room_id)
        except MatrixHttpError as e:
            raise AnsibleMatrixError("{} ({}): {} is not in the room and cannot join: {}".format(
                fq_alias, room_id, me, e))
        changes["joined"] = True
        room = RoomState(await api.room_state(room_id))

    # membership
    if wanted_members is not None:
        current = room.members
        current_levels = room.content("m.room.power_levels").get("users", {})
        keep = set(wanted_members) | {me} | {m for m, lvl in current_levels.items() if lvl >= OWNER_LEVEL}
        to_invite = sorted(m for m in wanted_members if m not in current and m != me)
        to_kick = sorted(m for m in current if m not in keep)

        async def act(action, mxid):
            try:
                await action(room_id, mxid)
                return mxid, None
            except MatrixHttpError as e:
                return mxid, str(e)

        for label, action, mxids in (("invited", api.invite, to_invite), ("kicked", api.kick, to_kick)):
            done = await asyncio.gather(*(act(action, m) for m in mxids))
            ok = [m for m, err in done if err is None]
            result["refused"] += [{"action": label, "mxid": m, "error": err} for m, err in done if err]
            if ok:
                changes[label] = ok

    # power levels: one complete event
    current_pl = room.content("m.room.power_levels")
    wanted_pl = wanted_power_levels(current_pl, me, wanted_members, power_level_override)
    if wanted_pl != current_pl:
        await api.put_state(room_id, "m.room.power_levels", wanted_pl)
        changes["power_levels"] = {
            k: {"old": current_pl.get(k), "new": wanted_pl.get(k)}
            for k in set(current_pl) | set(wanted_pl) if current_pl.get(k) != wanted_pl.get(k)
        }

    async def set_simple(event_type, key, value, label):
        if value is None:
            return
        old = room.content(event_type).get(key)
        if old != value:
            await api.put_state(room_id, event_type, {key: value})
            changes[label] = {"old": old, "new": value}

    async def set_avatar():
        old = room.content("m.room.avatar").get("url")
        new = await avatar_to_set(api, avatar, old)
        if new is not None:
            await api.put_state(room_id, "m.room.avatar", {"url": new})
            changes["avatar_url"] = {"old": old, "new": new}

    async def set_encryption():
        if encrypt and not room.encrypted:
            await api.put_state(room_id, "m.room.encryption", ENCRYPTION)
            changes["encryption"] = {"old": False, "new": True}
        elif not encrypt and room.encrypted:
            raise AnsibleMatrixError("{}: encryption, once enabled, cannot be disabled".format(fq_alias))

    async def set_visibility():
        if visibility is None:
            return
        old = await api.directory_visibility(room_id)
        if old != visibility:
            await api.set_directory_visibility(room_id, visibility)
            changes["visibility"] = {"old": old, "new": visibility}

    await asyncio.gather(
        set_simple("m.room.name", "name", name, "name"),
        set_simple("m.room.topic", "topic", topic, "topic"),
        set_avatar(),
        set_encryption(),
        set_visibility(),
    )

    result["changed"] = bool(changes)
    result["members"] = sorted((set(room.members) | set(changes.get("invited", [])))
                               - set(changes.get("kicked", [])))
    return result
