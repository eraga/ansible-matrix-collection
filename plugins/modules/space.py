import copy

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.space import AnsibleMatrixSpace
from ansible_collections.eraga.matrix.plugins.module_utils.room import *

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

DOCUMENTATION = '''
module: space
short_description: Manage Matrix Spaces
description:
    - Create and manage Matrix Spaces (next generation replacement for Communities)
notes:
    - This module replaces the deprecated community module as Matrix Spaces are the 
      recommended replacement for Communities/Groups
    - Spaces are actually rooms with special state events, offering better integration
      with Matrix clients
    - Unlike Communities (+), Spaces use room IDs (!) as identifiers
options:
    matrix_uri:
        description: Matrix homeserver URI
        required: true
        type: str
    matrix_user:
        description: Matrix user to authenticate as
        required: true
        type: str
    matrix_token:
        description: Matrix access token
        required: true
        type: str
    matrix_domain:
        description: Matrix server domain
        required: true
        type: str
    localpart:
        description: Space localpart (will be transformed to !localpart:domain)
        required: true
        type: str
    name:
        description: Display name for the space
        required: false
        type: str
    topic:
        description: Topic/description for the space
        required: false
        type: str
    avatar:
        description: URL to avatar image
        required: false
        type: str
    rooms:
        description: List of room IDs to add to space
        required: false
        type: list
    members:
        description: List of users to invite
        required: false
        type: list
    state:
        description: Whether the space should exist or not
        default: present
        choices: [ present, absent ]
        type: str
'''

EXAMPLES = '''
- name: Create a Matrix Space
  eraga.matrix.space:
    matrix_uri: "https://matrix.example.com"
    matrix_user: ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    localpart: myspace
    name: My Team Space
    topic: A space for our team collaboration
    avatar: "http://example.com/path/to/avatar.png"
    rooms:
      - "!roomid1:example.com"
      - "!roomid2:example.com" 
    members:
      - "@user1:example.com"
      - "@user2:example.com"

- name: Remove a Matrix Space
  eraga.matrix.space:
    matrix_uri: "https://matrix.example.com"
    matrix_user: ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    localpart: myspace
    state: absent
'''


async def run_module():
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        localpart=dict(type='str', required=True),
        name=dict(type='str', default=None),
        topic=dict(type='str', default=None),
        avatar=dict(type='str', default=None),
        visibility=dict(type='str', default='public', choices=['public', 'private']),
        rooms=dict(type='list', default=None),
        members=dict(type='list', default=None),

        state=dict(type="str", default="present",
                   choices=["present", "absent"])
    )

    result = dict(
        space={},
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

    space = AnsibleMatrixSpace(
        matrix_client=matrix_client,
        localpart=module.params['localpart'],
        changes=result['changed_fields']
    )

    async with space:
        try:
            exists = await space.exists()
            if exists:
                result['space'] = await space.get_state()

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
                await space.create_or_update(**params)
                result['changed'] = bool(result['changed_fields'])

            elif state == 'absent':
                await space.delete()
                result['changed'] = bool(result['changed_fields'])

            else:
                result['changed'] = bool(result['changed_fields'])
                module.fail_json(msg='Unsupported state={}'.format(state), **result)

            if result['changed']:
                result['space'] = await space.get_state()

        except AnsibleMatrixError as e:
            result['changed'] = bool(result['changed_fields'])
            module.fail_json(msg='MatrixError={}'.format(e), **result)

    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
