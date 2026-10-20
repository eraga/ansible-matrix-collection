from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.runner import CONNECTION_ARGS, USER_OPTIONS, make_api, run
from ansible_collections.eraga.matrix.plugins.module_utils.sync import sync_user

DOCUMENTATION = r'''
module: user
short_description: Sync the profile of one Matrix user
description:
  - Sets display name, avatar and admin flag, or deactivates the account.
  - A user the server does not have is left alone (C(exists=false)); it is never created.
  - For many users use M(eraga.matrix.users), which shares one connection.
options:
  state:
    type: str
    default: present
    choices: [present, deactivated]
'''

EXAMPLES = r'''
- name: User has an avatar from the web
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_token: "{{ token }}"
    matrix_domain: example.com
    login: johnny
    displayname: Джон Доу
    avatar: "https://example.com/path/to/web/image.png"

- name: User is deactivated
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_token: "{{ token }}"
    matrix_domain: example.com
    login: c3p0
    state: deactivated

- name: Read an account (check mode changes nothing)
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_token: "{{ token }}"
    matrix_domain: example.com
    login: d_trump
  check_mode: yes
  register: matrix_user
'''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            **CONNECTION_ARGS,
            **USER_OPTIONS,
            state=dict(type="str", default="present", choices=["present", "deactivated"]),
        ),
        supports_check_mode=True,
    )
    p = module.params

    async def go():
        api = make_api(module)
        try:
            result = await sync_user(api, p["login"], p["displayname"], p["avatar"], p["admin"], p["state"])
            result["user"] = await api.account(result["mxid"]) or {}
            return result
        finally:
            await api.close()

    try:
        result = run(go())
    except Exception as e:
        module.fail_json(msg="{}: {}".format(type(e).__name__, e))
    result["user"].pop("password_hash", None)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
