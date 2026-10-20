"""Unit tests of the sync core, no server needed.

Run from anywhere inside an ansible_collections/ tree:
    python tests/unit/test_sync.py
"""
import asyncio
import pathlib
import sys
import unittest

_here = pathlib.Path(__file__).resolve()
_root = next(p for p in _here.parents if p.name == "ansible_collections")
sys.path.insert(0, str(_root.parent))

from ansible_collections.eraga.matrix.plugins.module_utils.admin import (  # noqa: E402
    MatrixHttpError, filename_from_disposition)
from ansible_collections.eraga.matrix.plugins.module_utils.avatar import (  # noqa: E402
    Image, avatar_to_set, is_source_named, source_name)
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import _AnsibleMatrixObject  # noqa: E402
from ansible_collections.eraga.matrix.plugins.module_utils.sync import (  # noqa: E402
    sync_room, sync_user, wanted_power_levels)

ME = "@bot:x"


class FakeClient(_AnsibleMatrixObject):
    def __init__(self):
        super().__init__(domain="x")


class FakeApi:
    """MatrixApi stand-in: records every mutation."""

    def __init__(self, accounts=None, media=None, image=None, rooms=None):
        self.client = FakeClient()
        self.accounts = accounts or {}
        self.media = media or {}          # mxc -> (filename, bytes)
        self.img = image or Image(b"PNG", "image/png", source_name(b"SRC", "image/png"))
        self.rooms = rooms or {}          # alias -> (room_id, state events)
        self.calls = []

    def mxid(self, login):
        return self.client.login_to_id(login)

    async def me(self):
        return ME

    async def account(self, mxid):
        return self.accounts.get(mxid)

    async def is_active_user(self, mxid):
        acc = self.accounts.get(mxid)
        return acc is not None and not acc.get("deactivated")

    async def update_account(self, mxid, content):
        self.calls.append(("update_account", mxid, content))

    async def image(self, src):
        return self.img

    async def media_filename(self, mxc):
        return self.media[mxc][0] if mxc in self.media else None

    async def download(self, mxc):
        self.calls.append(("download", mxc))
        return self.media[mxc][1] if mxc in self.media else None

    async def upload(self, image):
        self.calls.append(("upload", image.name))
        return "mxc://x/new"

    async def resolve_alias(self, alias):
        return self.rooms[alias][0] if alias in self.rooms else None

    async def room_state(self, room_id):
        return next(s for rid, s in self.rooms.values() if rid == room_id)

    async def join(self, room_id):
        self.calls.append(("join", room_id))

    async def put_state(self, room_id, event_type, content, state_key=""):
        self.calls.append(("put_state", event_type, content))

    async def invite(self, room_id, mxid):
        self.calls.append(("invite", mxid))

    async def kick(self, room_id, mxid):
        self.calls.append(("kick", mxid))

    async def directory_visibility(self, room_id):
        return "private"

    async def set_directory_visibility(self, room_id, visibility):
        self.calls.append(("visibility", visibility))

    def actions(self, name):
        return [c for c in self.calls if c[0] == name]


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class Pure(unittest.TestCase):
    def test_disposition_forms(self):
        self.assertEqual(filename_from_disposition("inline; filename=a.svg.png"), "a.svg.png")
        self.assertEqual(filename_from_disposition('inline; filename="a b.png"'), "a b.png")
        self.assertEqual(filename_from_disposition("attachment; filename*=utf-8''%D0%B0.png"), "а.png")
        self.assertIsNone(filename_from_disposition(None))

    def test_source_name_is_recognised(self):
        name = source_name(b"svg bytes", "image/png")
        self.assertTrue(is_source_named(name))
        self.assertFalse(is_source_named("c3dd2ecf-4640.svg.png"))
        self.assertNotEqual(name, source_name(b"other svg", "image/png"))

    def test_login_is_lower_cased(self):
        self.assertEqual(FakeClient().login_to_id("Ekaterina_Mochalova"), "@ekaterina_mochalova:x")
        self.assertEqual(FakeClient().login_to_id("@Keep:x"), "@Keep:x")

    def test_power_levels_keep_rest_of_event_and_owners(self):
        current = {"ban": 50, "events": {"m.room.name": 50},
                   "users": {"@owner:x": 100, ME: 100, "@gone:x": 0}}
        wanted = wanted_power_levels(current, ME, {"@new:x": 0}, {"ban": 90, "invite": 10})
        self.assertEqual(wanted["events"], {"m.room.name": 50})
        self.assertEqual((wanted["ban"], wanted["invite"]), (90, 10))
        self.assertEqual(wanted["users"], {"@new:x": 0, "@owner:x": 100, ME: 100})


class Avatars(unittest.TestCase):
    def test_same_source_name_means_no_upload_and_no_download(self):
        api = FakeApi()
        api.media["mxc://x/cur"] = (api.img.name, b"rendered elsewhere")
        self.assertIsNone(run(avatar_to_set(api, "http://src", "mxc://x/cur")))
        self.assertEqual(api.calls, [])

    def test_legacy_upload_with_same_bytes_is_kept(self):
        api = FakeApi()
        api.media["mxc://x/cur"] = ("uuid?etag=1.png", b"PNG")
        self.assertIsNone(run(avatar_to_set(api, "http://src", "mxc://x/cur")))
        self.assertFalse(api.actions("upload"))

    def test_legacy_upload_with_other_bytes_is_replaced(self):
        api = FakeApi()
        api.media["mxc://x/cur"] = ("uuid.svg.png", b"rendered on another machine")
        self.assertEqual(run(avatar_to_set(api, "http://src", "mxc://x/cur")), "mxc://x/new")

    def test_source_named_but_different_source_is_replaced_without_download(self):
        api = FakeApi()
        api.media["mxc://x/cur"] = (source_name(b"OLD SRC", "image/png"), b"PNG")
        self.assertEqual(run(avatar_to_set(api, "http://src", "mxc://x/cur")), "mxc://x/new")
        self.assertFalse(api.actions("download"))


class Users(unittest.TestCase):
    def test_missing_user_gets_nothing(self):
        api = FakeApi()
        result = run(sync_user(api, "Simon_Lee", "Simon", "http://src"))
        self.assertFalse(result["exists"])
        self.assertFalse(result["changed"])
        self.assertEqual(api.calls, [])

    def test_changes_go_in_one_update(self):
        api = FakeApi(accounts={"@ivan:x": {"displayname": "Old", "avatar_url": None}})
        result = run(sync_user(api, "Ivan", "Ivan K", "http://src"))
        self.assertTrue(result["changed"])
        self.assertEqual(api.actions("update_account"),
                         [("update_account", "@ivan:x", {"displayname": "Ivan K", "avatar_url": "mxc://x/new"})])

    def test_deactivated_user_is_left_alone(self):
        api = FakeApi(accounts={"@ivan:x": {"displayname": "Old", "deactivated": True}})
        self.assertFalse(run(sync_user(api, "ivan", "New", "http://src"))["changed"])
        self.assertEqual(api.calls, [])


def member(mxid, membership="join"):
    return {"type": "m.room.member", "state_key": mxid, "content": {"membership": membership}}


class Rooms(unittest.TestCase):
    def room_api(self, events, accounts):
        state = [member(ME), {"type": "m.room.encryption", "state_key": "", "content": {"algorithm": "a"}}] + events
        return FakeApi(accounts=accounts, rooms={"#r:x": ("!r:x", state)})

    def test_membership_follows_list_and_skips_absent_users(self):
        pl = {"type": "m.room.power_levels", "state_key": "",
              "content": {"users": {ME: 100, "@owner:x": 100, "@left:x": 0}}}
        api = self.room_api(
            [pl, member("@owner:x"), member("@extra:x"), member("@Bogus:x", "invite"), member("@stay:x")],
            accounts={"@stay:x": {}, "@new:x": {}, "@owner:x": {}, "@extra:x": {}})
        result = run(sync_room(api, "r", encrypt=True,
                               room_members={"stay": 0, "new": 0, "Ghost": 0}))
        self.assertEqual(api.actions("invite"), [("invite", "@new:x")])
        self.assertEqual(sorted(api.actions("kick")), [("kick", "@Bogus:x"), ("kick", "@extra:x")])
        self.assertEqual(result["absent_users"], ["Ghost"])
        levels = [c[2] for c in api.actions("put_state") if c[1] == "m.room.power_levels"]
        self.assertEqual(levels, [{"users": {"@stay:x": 0, "@new:x": 0, ME: 100, "@owner:x": 100}}])

    def test_unchanged_room_makes_no_calls(self):
        pl = {"type": "m.room.power_levels", "state_key": "", "content": {"users": {ME: 100, "@stay:x": 0}, "ban": 90}}
        name = {"type": "m.room.name", "state_key": "", "content": {"name": "N"}}
        api = self.room_api([pl, name, member("@stay:x")], accounts={"@stay:x": {}})
        result = run(sync_room(api, "r", name="N", encrypt=True, room_members={"stay": 0},
                               power_level_override={"ban": 90}))
        self.assertFalse(result["changed"], result["changed_fields"])
        self.assertEqual(api.calls, [])

    def test_lookup_failure_does_not_kick(self):
        class Flaky(FakeApi):
            async def is_active_user(self, mxid):
                raise MatrixHttpError("GET", "/u", 502, {"error": "bad gateway"})

        api = Flaky(accounts={}, rooms={"#r:x": ("!r:x", [member(ME), member("@stay:x")])})
        with self.assertRaises(MatrixHttpError):
            run(sync_room(api, "r", room_members={"stay": 0}))
        self.assertFalse(api.actions("kick"))


if __name__ == "__main__":
    unittest.main()
