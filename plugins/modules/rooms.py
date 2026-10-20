from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.runner import (
    CONNECTION_ARGS, ROOM_OPTIONS, make_api, run, run_all)
from ansible_collections.eraga.matrix.plugins.module_utils.sync import sync_room

DOCUMENTATION = r'''
module: rooms
short_description: Ensure many Matrix rooms in one go
description:
  - Each listed room exists with the given name, topic, avatar, encryption,
    visibility, power levels and members; options as in M(eraga.matrix.room).
  - C(room_members) is the complete member list. Users the server does not
    have are not invited and get no power level; they are listed per room in
    C(absent_users). Members not listed are kicked, except room owners
    (power level 100), whom Matrix does not let anyone demote.
  - Reads room state through the Synapse admin API (the token must be a
    server admin's); no client /sync.
options:
  rooms:
    description: Rooms to ensure, each with C(alias) and the options of M(eraga.matrix.room).
    type: list
    elements: dict
    required: true
  concurrency:
    description: Requests in flight at once.
    type: int
    default: 8
'''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            **CONNECTION_ARGS,
            rooms=dict(type="list", elements="dict", required=True, options=ROOM_OPTIONS),
            concurrency=dict(type="int", default=8),
        ),
        supports_check_mode=True,
    )

    async def go():
        api = make_api(module, module.params["concurrency"])
        try:
            return await run_all(module.params["rooms"], lambda r: sync_room(api, **r), "alias")
        finally:
            await api.close()

    results, failed = run(go())
    # A refused invite or kick (a user banned from the room, say) is the
    # room's business, not a broken sync: warn, do not fail.
    for r in results:
        for f in r["refused"]:
            module.warn("{}: {} {} failed: {}".format(r["alias"], f["action"], f["mxid"], f["error"]))
    changed = [r for r in results if r["changed"]]
    out = dict(
        changed=bool(changed),
        rooms=results,
        updated=[r["alias"] for r in changed],
        errors=failed,
    )
    if failed:
        module.fail_json(msg="{} of {} rooms failed".format(len(failed), len(module.params["rooms"])), **out)
    module.exit_json(**out)


if __name__ == "__main__":
    main()
