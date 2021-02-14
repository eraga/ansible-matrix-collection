import copy

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.community import AnsibleMatrixCommunity
from ansible_collections.eraga.matrix.plugins.module_utils.room import *

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

"""
- name: Community exists at matrix server with avatar from link
  eraga.matrix.community:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    # localpart will be transformed to +{{localpart}}:{{matrix_domain}} 
    localpart: test     
    name: Test Community
    avatar: "http://example.com/path/to/local/image.png"
    description: This community is managed by Ansible      
    long_description: | 
      # ¡Hola!
      Long description that supports markdown.      
    members:
      - maria
      - helga
      - m0rty

- name: Community does not exist
  eraga.matrix.community:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    localpart: test     
    state: absent    
"""


async def run_module():
    # define the available arguments/parameters that a user can pass to
    # the module
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        localpart=dict(type='str', required=True),
        name=dict(type='str', default=None),
        avatar=dict(type='str', default=None),
        description=dict(type='str', default=None),
        long_description=dict(type='str', default=None),
        visibility=dict(type='str', default=None),
        rooms=dict(type='list', default=None),
        members=dict(type='list', default=None),

        state=dict(type="str", default="present",
                   choices=["present", "absent"])
    )

    result = dict(
        community={},
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

    community = AnsibleMatrixCommunity(
        matrix_client=matrix_client,
        localpart=module.params['localpart'],
        changes=result['changed_fields']
    )

    async with community:
        try:
            exists = community.profile is not None
            if exists:
                result['community'] = community.summary.dict()

            if module.check_mode:
                module.exit_json(**result)
                return result

            params = copy.deepcopy(module.params)
            del params['matrix_uri']
            del params['matrix_user']
            del params['matrix_domain']
            del params['matrix_token']
            del params['localpart']
            del params['state']

            if state == 'present':
                await community.update(**params)
                result['changed'] = bool(result['changed_fields'])

            elif state == 'absent':
                await community.delete()
                result['changed'] = bool(result['changed_fields'])

            else:
                result['changed'] = bool(result['changed_fields'])
                module.fail_json(msg='Unsupported state={}'.format(state), **result)

            if result['changed']:
                result['community'] = community.summary.dict()

        except AnsibleMatrixError as e:
            result['changed'] = bool(result['changed_fields'])
            module.fail_json(msg='MatrixError={}'.format(e), **result)
        finally:
            await community.__aexit__()

    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
