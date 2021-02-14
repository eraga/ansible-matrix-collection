import asyncio
import copy

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.room import *
from ansible_collections.eraga.matrix.plugins.module_utils.user import AnsibleMatrixUser

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

"""
- name: User exists at matrix server  wit avatar from file system
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    login: ivan     
    displayname: Ivan Kalinin     
    avatar: "/path/to/local/image.png"
    
- name: User exists at matrix server
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    login: johnny     
    displayname: Джон Доу     
    avatar: "http:/example.com/path/to/web/image.png"     

- name: User exists and deactivated at matrix server
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    login: c3p0     
    state: deactivated
    
- name: Get account info from Matrix server
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    login: d_trump     
  check_mode: yes
  register: matrix_user 
"""


async def run_module():
    # define the available arguments/parameters that a user can pass to
    # the module
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        login=dict(type='str', required=True),
        displayname=dict(type='str', default=None),
        avatar=dict(type='str', default=None),

        admin=dict(type='bool', default=None),

        state=dict(type="str", default="present",
                   choices=["present", "deactivated"])
    )

    result = dict(
        user={},
        changed=False,
        changed_fields={}
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    state = module.params['state']

    matrix_client = AnsibleMatrixClient(
        domain=module.params["matrix_domain"],
        uri=module.params['matrix_uri'],
        token=module.params['matrix_token'],
        user=module.params['matrix_user']
    )

    user = AnsibleMatrixUser(
        matrix_client=matrix_client,
        login=module.params['login'],
        changes=result['changed_fields']
    )

    async with user:
        try:
            exists = user.account is not None
            if exists:
                result['user'] = user.account.dict()

            if module.check_mode:
                module.exit_json(**result)
                return result

            params = copy.deepcopy(module.params)
            del params['matrix_uri']
            del params['matrix_user']
            del params['matrix_domain']
            del params['matrix_token']
            del params['login']
            del params['state']

            if state == 'present':
                await user.update(**params)
                result['changed'] = bool(result['changed_fields'])

            elif state == 'deactivated':
                await user.set_deactivated(True)
                result['changed'] = bool(result['changed_fields'])

            else:
                result['changed'] = bool(result['changed_fields'])
                module.fail_json(msg='Unsupported state={}'.format(state), **result)

            if result['changed']:
                result['user'] = user.account.dict()

        except AnsibleMatrixError as e:
            result['changed'] = bool(result['changed_fields'])
            module.fail_json(msg='MatrixError={}'.format(e), **result)
        finally:
            await user.__aexit__()

    # print(result)
    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
