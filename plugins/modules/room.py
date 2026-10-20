from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.runner import CONNECTION_ARGS, ROOM_OPTIONS, make_api, run
from ansible_collections.eraga.matrix.plugins.module_utils.sync import sync_room

DOCUMENTATION = r'''
module: room
short_description: Ensure one Matrix room
description:
  - The room exists with the given name, topic, avatar, encryption,
    visibility, power levels and members, or is deleted (C(state=absent)).
  - C(room_members) maps logins to power levels and is the complete member
    list. Users the server does not have are not invited (see
    C(absent_users)); members not listed are kicked, except owners (level 100).
  - For many rooms use M(eraga.matrix.rooms), which shares one connection.
'''

EXAMPLES = r'''
- name: Project room
  eraga.matrix.room:
    matrix_uri: "https://matrix.example.com"
    matrix_token: "{{ token }}"
    matrix_domain: example.com
    alias: example_room
    name: Example Room
    topic: This is room managed by ansible
    federate: no
    visibility: private
    preset: private_chat
    encrypt: yes
    avatar: "https://example.com/path/to/avatar.png"
    room_members:
      admin_login: 90
      user_login: 0
    power_level_override:
      events_default: 0
      state_default: 50
      ban: 50
      kick: 50
      redact: 50
      invite: 50
'''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            **CONNECTION_ARGS,
            **ROOM_OPTIONS,
            state=dict(type="str", default="present", choices=["present", "absent"]),
        ),
        supports_check_mode=True,
    )
    spec = {k: module.params[k] for k in list(ROOM_OPTIONS) + ["state"]}

    async def go():
        api = make_api(module)
        try:
            return await sync_room(api, **spec)
        finally:
            await api.close()

    try:
        result = run(go())
    except Exception as e:
        module.fail_json(msg="{}: {}".format(type(e).__name__, e))
    for f in result["refused"]:
        module.warn("{} {} failed: {}".format(f["action"], f["mxid"], f["error"]))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
